"""Confirmed answers and conservative, human-reviewed eligibility checks."""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (ApplicantProfile, ApplicantProfileHistory, JobRequirementReview,
    EligibilityAssessment, Job, JobEvidence, Resume, ApplicationPreparation)
from app.discovery.matching import contains, target_role_matches
from app.discovery.location import INDIA_LOCATIONS
from app.discovery.service import get_profile
from app.resumes import master_resume_id, resume_contains, skills_list, assess

router = APIRouter(tags=['Applicant profile and eligibility'])
DB = Annotated[Session, Depends(get_db)]
Mode = Literal['remote', 'hybrid', 'on_site']

def now(): return datetime.now(timezone.utc)
def owner(): return os.getenv('AUTH_USERNAME', 'workspace-owner')

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class ApplicantData(Strict):
    given_name: str | None = Field(None, min_length=1, max_length=100)
    family_name: str | None = Field(None, min_length=1, max_length=100)
    full_name: str | None = Field(None, min_length=1, max_length=150)
    email: str | None = Field(None, max_length=254)
    phone: str | None = Field(None, max_length=30)
    current_city: str | None = Field(None, min_length=1, max_length=100)
    linkedin_url: str | None = Field(None, max_length=500)
    portfolio_url: str | None = Field(None, max_length=500)
    india_work_authorized: StrictBool | None = None
    requires_sponsorship: StrictBool | None = None
    willing_relocate_india: StrictBool | None = None
    work_modes: list[Mode] = Field(default_factory=list, max_length=3)
    experience_years: float | None = Field(None, ge=0, le=60, allow_inf_nan=False)
    notice_days: int | None = Field(None, ge=0, le=365)
    available_from: date | None = None
    expected_ctc_lpa: float | None = Field(None, ge=0, le=1000, allow_inf_nan=False)

    @field_validator('email')
    @classmethod
    def email_format(cls, value):
        if value is not None and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
            raise ValueError('Use a valid email address or leave unknown')
        return value

    @field_validator('phone')
    @classmethod
    def phone_format(cls,value):
        if value is not None and (not re.fullmatch(r'[+()\d .-]+',value) or not 7 <= len(re.sub(r'\D','',value)) <= 15):
            raise ValueError('Use a phone number with 7 to 15 digits')
        return value

    @field_validator('linkedin_url','portfolio_url')
    @classmethod
    def valid_url(cls,value):
        if value is not None:
            u=urlsplit(value)
            if u.scheme!='https' or not u.netloc or u.username or u.password or any(c.isspace() for c in value):
                raise ValueError('Use an HTTPS profile URL without credentials')
        return value

    @field_validator('work_modes')
    @classmethod
    def unique_modes(cls,value): return list(dict.fromkeys(value))

class ProfileInput(Strict):
    expected_version: int = Field(ge=0)
    confirmed: Literal[True]
    data: ApplicantData

class Requirements(Strict):
    required_skills: list[str] = Field(default_factory=list,max_length=100)
    preferred_skills: list[str] = Field(default_factory=list,max_length=100)
    minimum_experience_years: float | None = Field(None, ge=0, le=60, allow_inf_nan=False)
    india_eligible: StrictBool | None = None
    work_mode: Mode | None = None
    city: str | None = Field(None,min_length=1,max_length=100)
    no_sponsorship: StrictBool | None = None
    maximum_notice_days: int | None = Field(None,ge=0,le=365)
    start_by: date | None = None
    unresolved_requirements: list[str] = Field(default_factory=list,max_length=40)

    @field_validator('required_skills','preferred_skills','unresolved_requirements')
    @classmethod
    def clean_list(cls,values):
        if any(not v.strip() or len(v)>500 for v in values):
            raise ValueError('Entries must be nonblank and at most 500 characters')
        return list(dict.fromkeys(v.strip() for v in values))

class RequirementInput(Strict):
    expected_version: int = Field(ge=0)
    source_hash: str = Field(min_length=64,max_length=64)
    confirmed: Literal[True]
    review_note: str = Field(min_length=1,max_length=3000)
    data: Requirements

def job_for(db,job_id,lock=False):
    stmt=select(Job).where(Job.job_id==job_id)
    job=db.scalar(stmt.with_for_update() if lock else stmt)
    if job is None: raise HTTPException(404,'Job not found')
    return job

def source_hash(db,job):
    evidence=db.get(JobEvidence,job.job_id)
    data={key:getattr(job,key,None) for key in ['job_id','company_id','role','location','required_skills','source_url']}
    data['description']=evidence.description if evidence else ''
    return sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def profile_response(record):
    return {'version':record.version if record else 0,'confirmed_at':record.confirmed_at if record else None,
        'confirmed_by':record.confirmed_by if record else None,
        'data':record.data if record else ApplicantData().model_dump(mode='json')}

@router.get('/applicant-profile')
def read_profile(db:DB): return profile_response(db.get(ApplicantProfile,1))

@router.put('/applicant-profile')
def save_profile(payload:ProfileInput,db:DB):
    record=db.scalar(select(ApplicantProfile).where(ApplicantProfile.id==1).with_for_update())
    version=record.version if record else 0
    if payload.expected_version!=version: raise HTTPException(409,'Profile changed; reload before saving')
    if record is None:
        record=ApplicantProfile(id=1)
        db.add(record)
    record.version=version+1
    record.data=payload.data.model_dump(mode='json')
    record.confirmed_at=now(); record.confirmed_by=owner()
    db.add(ApplicantProfileHistory(version=record.version,data=record.data,confirmed_at=record.confirmed_at,confirmed_by=record.confirmed_by))
    try: db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409,'Profile changed; reload before saving') from exc
    return profile_response(record)

@router.get('/applicant-profile/history')
def profile_history(db:DB,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    return [profile_response(r) for r in db.scalars(select(ApplicantProfileHistory).order_by(ApplicantProfileHistory.version.desc()).offset(offset).limit(limit))]

QUESTIONS={
    'given_name':'First name','family_name':'Last name','full_name':'Full name','email':'Email address','phone':'Phone number','current_city':'Current city',
    'linkedin_url':'LinkedIn profile','portfolio_url':'Portfolio website',
    'india_work_authorized':'Are you currently authorized to work in India?',
    'requires_sponsorship':'Do you require employer sponsorship?',
    'willing_relocate_india':'Are you willing to relocate within India?',
    'work_modes':'Accepted work arrangements','experience_years':'Total relevant professional experience in years',
    'notice_days':'Notice period in calendar days','available_from':'Earliest confirmed availability date',
    'expected_ctc_lpa':'Expected annual CTC in INR lakhs per annum'}

def answers(db):
    record=db.get(ApplicantProfile,1)
    return {'profile_version':record.version if record else 0,
        'answers':[{'field':k,'question':label,'answer':record.data[k],'confirmed_at':record.confirmed_at.isoformat()}
            for k,label in QUESTIONS.items() if record and record.data.get(k) is not None and record.data.get(k)!=[]],
        'note':'Use only for the same question and units. Unknown answers are omitted. Nothing is sent or autofilled.'}

@router.get('/applicant-profile/answers')
def reusable_answers(db:DB): return answers(db)

VOCABULARY=['Python','Java','JavaScript','TypeScript','SQL','PostgreSQL','MongoDB','Docker','Linux','React','Next.js',
    'Node.js','Express.js','FastAPI','REST APIs','RAG','LangChain','MCP','Kafka','Spark','Airflow','AWS','Azure','GCP',
    'Snowflake','Databricks','ETL','dbt','Kubernetes','Redis','TensorFlow','PyTorch','LLMs','SIP','Twilio','Amazon Connect']
PREFERRED=re.compile(r'preferred|nice.to.have|bonus|a plus|good.to.have|desirable',re.I)
HEAD_REQUIRED=re.compile(r'^(?:required skills|mandatory skills|requirements|qualifications|what you bring(?: to the role)?|must.have|essential skills)\s*:?',re.I)
NEGATED=re.compile(r'not required|no .{0,30} required|optional|not mandatory',re.I)

def extract_requirements(job,description):
    data=Requirements(required_skills=skills_list(job.required_skills)).model_dump(mode='json')
    evidence=[]; section=None
    location=job.location or ''
    if any(contains(location,x) for x in INDIA_LOCATIONS): data['india_eligible']=True
    city=next((x for x in INDIA_LOCATIONS if x!='India' and contains(location,x)),None)
    data['city']=city
    for raw in (description or '').splitlines():
        line=raw.strip(' \t-•')
        if not line: continue
        if re.match(r'^(responsibilities|benefits|about us|what you.ll do)\b',line,re.I): section=None
        preferred=bool(PREFERRED.search(line))
        if preferred and re.match(r'^(preferred|nice.to.have|bonus|good.to.have)',line,re.I): section='preferred'
        elif HEAD_REQUIRED.match(line): section='required'
        category='preferred' if preferred or section=='preferred' else 'required' if section=='required' or re.search(r'\bmust|required|mandatory\b',line,re.I) else None
        if NEGATED.search(line):
            if category: data['unresolved_requirements'].append(line[:500])
            continue
        recognized=False
        if category:
            found=[s for s in VOCABULARY if resume_contains(line,s.casefold())]
            if found:
                data[category+'_skills'].extend(found); recognized=True
                evidence.append({'field':category+'_skills','quote':line[:1000]})
        if category=='required':
            years=re.search(r'\b(\d+(?:\.\d+)?)(?:\s*[-–]\s*\d+)?\s*\+?\s*(?:years?|yrs?)\b.{0,35}\bexperience\b',line,re.I)
            if years and float(years.group(1))<=60:
                data['minimum_experience_years']=max(data['minimum_experience_years'] or 0,float(years.group(1)))
                evidence.append({'field':'minimum_experience_years','quote':line[:1000]}); recognized=True
            if not recognized and not HEAD_REQUIRED.fullmatch(line): data['unresolved_requirements'].append(line[:500])
        # Outside a required section these are only suggestions and still require review.
        if not preferred and re.search(r'(?:no|without) (?:visa )?sponsorship|cannot (?:provide|offer) sponsorship',line,re.I):
            data['no_sponsorship']=True; evidence.append({'field':'no_sponsorship','quote':line[:1000]})
    modes=[]
    if re.search(r'\bhybrid\b',location,re.I): modes.append('hybrid')
    if re.search(r'\bremote\b',location,re.I): modes.append('remote')
    if re.search(r'\bon[ -]?site\b',location,re.I): modes.append('on_site')
    if len(modes)==1: data['work_mode']=modes[0]
    elif len(modes)>1: data['unresolved_requirements'].append('Multiple work arrangements in location; confirm the actual requirement')
    for key in ['required_skills','preferred_skills']: data[key]=skills_list(','.join(data[key]))
    data['unresolved_requirements']=list(dict.fromkeys(data['unresolved_requirements']))[:40]
    return {'data':data,'evidence':evidence,'note':'Suggestions only. Review the live posting; extraction does not certify requirements or eligibility.'}

@router.get('/jobs/{job_id}/requirements')
def read_requirements(job_id:str,db:DB):
    job=job_for(db,job_id); record=db.get(JobRequirementReview,job_id); ev=db.get(JobEvidence,job_id)
    current_hash=source_hash(db,job)
    return {'source_hash':current_hash,'version':record.version if record else 0,
        'review_current':bool(record and record.source_hash==current_hash),
        'reviewed':record.data if record else None,
        'suggested':extract_requirements(job,ev.description if ev else ''),
        'description':ev.description if ev else '', 'source_url':job.source_url,
        'reviewed_at':record.reviewed_at if record else None,
        'history':record.history if record else []}

@router.put('/jobs/{job_id}/requirements')
def review_requirements(job_id:str,payload:RequirementInput,db:DB):
    job=job_for(db,job_id,True)
    prep=db.get(ApplicationPreparation,job_id)
    if (prep and prep.submitted_on) or job.status in ('Applied','Interview','Offer','Withdrawn'):
        raise HTTPException(409,'Submitted application requirements are frozen')
    record=db.get(JobRequirementReview,job_id); version=record.version if record else 0
    if payload.expected_version!=version or payload.source_hash!=source_hash(db,job):
        raise HTTPException(409,'Job or requirements changed; reload before reviewing')
    if record is None:
        record=JobRequirementReview(job_id=job_id,history=[]); db.add(record)
    else:
        record.history=[*record.history,{'version':record.version,'data':record.data,'source_hash':record.source_hash,
            'reviewed_at':record.reviewed_at.isoformat(),'reviewed_by':record.reviewed_by}]
    record.version=version+1; record.data=payload.data.model_dump(mode='json')
    record.data['review_note']=payload.review_note
    record.reviewed_at=now(); record.reviewed_by=owner()
    job.required_skills=', '.join(payload.data.required_skills) or None
    with db.no_autoflush:
        record.source_hash=source_hash(db,job)
    # Preserve the existing score rule; eligibility never silently changes application outcomes.
    assess(db,job)
    db.commit()
    return read_requirements(job_id,db)

def city_key(value):
    value=(value or '').strip().casefold()
    return {'bangalore':'bengaluru','gurgaon':'gurugram'}.get(value,value)

def eligibility(db,job):
    profile=db.get(ApplicantProfile,1); review=db.get(JobRequirementReview,job.job_id)
    checks=[]
    def add(key,state,message,evidence=None): checks.append({'key':key,'state':state,'message':message,'evidence':evidence})
    current_hash=source_hash(db,job)
    reviewed=bool(review and review.source_hash==current_hash)
    add('profile','pass' if profile else 'unknown','Confirmed applicant profile available' if profile else 'Save and confirm your applicant profile')
    add('requirements','pass' if reviewed else 'unknown','Requirements reviewed against current job' if reviewed else 'Review current job requirements before relying on eligibility')
    roles=get_profile(db).target_roles
    if roles: add('designation','pass' if target_role_matches(job.role,roles) else 'fail','Compare job title with current target designations',roles)
    p=profile.data if profile else {}; r=review.data if reviewed else {}
    if reviewed:
        india=r.get('india_eligible')
        add('india_location','pass' if india is True else 'fail' if india is False else 'unknown','India-based applicant eligibility',india)
        authorized=p.get('india_work_authorized'); sponsor=p.get('requires_sponsorship')
        if authorized is True: add('authorization','pass','Applicant confirmed current India work authorization')
        elif authorized is False and r.get('no_sponsorship') is True: add('authorization','fail','Not currently authorized and employer does not sponsor')
        else: add('authorization','unknown','Confirm India work authorization or employer sponsorship eligibility')
        if sponsor is True:
            add('sponsorship','fail' if r.get('no_sponsorship') is True else 'pass' if r.get('no_sponsorship') is False else 'unknown','Compare confirmed sponsorship need with employer policy',r.get('no_sponsorship'))
        elif sponsor is None and r.get('no_sponsorship') is True:
            add('sponsorship','unknown','Confirm whether employer sponsorship is required')
        minimum=r.get('minimum_experience_years')
        if minimum is not None:
            actual=p.get('experience_years')
            add('experience','unknown' if actual is None else 'pass' if actual>=minimum else 'fail',f'Minimum experience {minimum} years; confirmed experience {actual}',minimum)
        mode=r.get('work_mode'); accepted=p.get('work_modes',[])
        add('work_mode','unknown' if mode is None or not accepted else 'pass' if mode in accepted else 'fail','Compare required work arrangement with confirmed preferences',{'required':mode,'accepted':accepted})
        if mode in ('on_site','hybrid'):
            same=bool(r.get('city') and p.get('current_city') and city_key(r['city'])==city_key(p['current_city']))
            relocate=p.get('willing_relocate_india')
            state='pass' if same or relocate is True else 'fail' if relocate is False and r.get('city') and p.get('current_city') else 'unknown'
            add('relocation',state,'Confirm ability to work in the required city',{'job_city':r.get('city'),'current_city':p.get('current_city')})
        maximum=r.get('maximum_notice_days')
        if maximum is not None:
            notice=p.get('notice_days')
            add('notice','unknown' if notice is None else 'pass' if notice<=maximum else 'fail',f'Maximum notice {maximum} days; confirmed notice {notice}',maximum)
        if r.get('start_by'):
            available=p.get('available_from')
            add('availability','unknown' if available is None else 'pass' if available<=r['start_by'] else 'fail','Compare confirmed availability with required start date',{'start_by':r['start_by'],'available_from':available})
        for item in r.get('unresolved_requirements',[]): add('unresolved','unknown',item)
    resume=db.get(Resume,master_resume_id(db)) if master_resume_id(db) else None
    required=skills_list(','.join(r.get('required_skills',[]))) if reviewed else []
    preferred=skills_list(','.join(r.get('preferred_skills',[]))) if reviewed else []
    matched=[s for s in required if resume and resume_contains(resume.text,s)]
    status='not_eligible' if any(c['state']=='fail' for c in checks) else 'needs_clarification' if any(c['state']=='unknown' for c in checks) else 'eligible'
    return {'status':status,'checks':checks,'profile_version':profile.version if profile else 0,
        'requirements_version':review.version if review else 0,'requirements_current':reviewed,'source_hash':current_hash,
        'required_skill_coverage':{'resume_id':resume.id if resume else None,'matched':matched,'missing':[s for s in required if s not in matched],
            'percent':100*len(matched)/len(required) if required and resume else None},
        'preferred_skill_matches':[s for s in preferred if resume and resume_contains(resume.text,s)],
        'note':'Eligibility covers reviewed non-skill conditions only, not hiring probability. Required-skill coverage, job approval, live posting checks and exact resume approval remain separate.'}

@router.get('/jobs/{job_id}/eligibility')
def read_eligibility(job_id:str,db:DB): return eligibility(db,job_for(db,job_id))

@router.post('/jobs/{job_id}/eligibility/assess',status_code=201)
def record_eligibility(job_id:str,db:DB):
    job=job_for(db,job_id,True); result=eligibility(db,job)
    record=EligibilityAssessment(id=str(uuid4()),job_id=job_id,created_at=now(),result=result)
    db.add(record); db.commit()
    return {'id':record.id,'created_at':record.created_at,**result}

@router.get('/jobs/{job_id}/eligibility/history')
def eligibility_history(job_id:str,db:DB,limit:int=Query(20,ge=1,le=100)):
    job_for(db,job_id)
    return [{'id':r.id,'created_at':r.created_at,**r.result} for r in db.scalars(select(EligibilityAssessment)
        .where(EligibilityAssessment.job_id==job_id).order_by(EligibilityAssessment.created_at.desc()).limit(limit))]

@router.get('/jobs/{job_id}/application-answers')
def application_answers(job_id:str,db:DB):
    return {**answers(db),'eligibility':eligibility(db,job_for(db,job_id))}
