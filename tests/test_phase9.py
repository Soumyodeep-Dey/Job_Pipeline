from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Job, Resume, ApplicantProfileHistory
from app.phase9 import extract_requirements


@pytest.fixture
def scenario(client,session_factory,monkeypatch):
    monkeypatch.setenv('MASTER_RESUME_ID','master9')
    with session_factory() as db:
        db.add(Resume(id='master9',filename='master.pdf',text='Candidate\nPython SQL Docker\nBuilt Python APIs with SQL'))
        db.commit()
    assert client.post('/jobs',json={'job_id':'elig','company':'Atlan','role':'Data Engineer',
        'location':'Bengaluru, India','required_skills':'Python, SQL'}).status_code==201
    return client


def save_profile(c,**changes):
    current=c.get('/applicant-profile').json()
    data={'india_work_authorized':True,'requires_sponsorship':False,'current_city':'Bangalore',
          'work_modes':['hybrid','remote'],'willing_relocate_india':False,'experience_years':2,
          'notice_days':15,'available_from':'2026-11-10','expected_ctc_lpa':8.5}
    data.update(changes)
    return c.put('/applicant-profile',json={'expected_version':current['version'],'confirmed':True,'data':data})


def review(c,**changes):
    current=c.get('/jobs/elig/requirements').json()
    data={'required_skills':['Python','SQL'],'preferred_skills':['Kafka'],'india_eligible':True,
          'work_mode':'hybrid','city':'Bengaluru','minimum_experience_years':1,'no_sponsorship':True,
          'maximum_notice_days':30,'start_by':'2026-11-20','unresolved_requirements':[]}
    data.update(changes)
    return c.put('/jobs/elig/requirements',json={'expected_version':current['version'],'source_hash':current['source_hash'],
        'confirmed':True,'review_note':'Reviewed synthetic employer posting','data':data})


def test_profile_confirmation_unknowns_units_and_history(scenario,session_factory):
    c=scenario
    assert c.get('/applicant-profile').json()['version']==0
    assert c.get('/applicant-profile/answers').json()['answers']==[]
    assert c.put('/applicant-profile',json={'expected_version':0,'confirmed':False,'data':{}}).status_code==422
    response=save_profile(c,notice_days=0)
    assert response.status_code==200,response.text
    answers={r['field']:r for r in c.get('/applicant-profile/answers').json()['answers']}
    assert answers['notice_days']['answer']==0
    assert answers['requires_sponsorship']['answer'] is False
    assert 'INR lakhs per annum' in answers['expected_ctc_lpa']['question']
    assert 'email' not in answers
    assert c.put('/applicant-profile',json={'expected_version':0,'confirmed':True,'data':{}}).status_code==409
    assert save_profile(c,experience_years=3).status_code==200
    with session_factory() as db:
        assert len(db.scalars(select(ApplicantProfileHistory)).all())==2
    assert c.put('/applicant-profile',json={'expected_version':2,'confirmed':True,'data':{'email':'not an email'}}).status_code==422


def test_extractor_distinguishes_required_preferred_and_negated():
    job=SimpleNamespace(location='Remote India',required_skills=None)
    parsed=extract_requirements(job,'Requirements\nPython and SQL\nMinimum 2 years of experience\nBachelor degree required\nPreferred skills: Kafka\n5 years of experience preferred\nBenefits\nOur company has 20 years of history')['data']
    assert set(parsed['required_skills'])=={'python','sql'}
    assert parsed['preferred_skills']==['kafka']
    assert parsed['minimum_experience_years']==2
    assert any('Bachelor' in s for s in parsed['unresolved_requirements'])
    assert parsed['work_mode']=='remote'
    negative=extract_requirements(job,'Required skills: Python not required')['data']
    assert not negative['required_skills']
    assert negative['unresolved_requirements']
    assert extract_requirements(SimpleNamespace(location='Remote',required_skills=None),'')['data']['india_eligible'] is None


def test_eligible_does_not_count_preferred_gaps(scenario):
    c=scenario; assert save_profile(c).status_code==200; assert review(c).status_code==200
    result=c.get('/jobs/elig/eligibility').json()
    assert result['status']=='eligible',result
    assert result['required_skill_coverage']['percent']==100
    assert result['preferred_skill_matches']==[]
    record=c.post('/jobs/elig/eligibility/assess')
    assert record.status_code==201
    assert len(c.get('/jobs/elig/eligibility/history').json())==1
    assert c.get('/jobs/elig/application-answers').json()['profile_version']==1


@pytest.mark.parametrize('changes,key,status',[
    ({'experience_years':0.5},'experience','not_eligible'),
    ({'experience_years':None},'experience','needs_clarification'),
    ({'india_work_authorized':None},'authorization','needs_clarification'),
    ({'requires_sponsorship':True},'sponsorship','not_eligible'),
    ({'notice_days':60},'notice','not_eligible'),
    ({'available_from':'2026-12-01'},'availability','not_eligible'),
    ({'work_modes':['remote']},'work_mode','not_eligible'),
    ({'current_city':'Kolkata'},'relocation','not_eligible'),
    ({'current_city':'Kolkata','willing_relocate_india':None},'relocation','needs_clarification')])
def test_confirmed_constraints_drive_decision(scenario,changes,key,status):
    c=scenario; save_profile(c,**changes); review(c)
    result=c.get('/jobs/elig/eligibility').json()
    assert result['status']==status,result
    assert any(r['key']==key and r['state']!='pass' for r in result['checks'])


def test_unknown_and_stale_reviews_block_even_high_score(scenario,session_factory):
    c=scenario; save_profile(c)
    assert c.get('/jobs/elig/eligibility').json()['status']=='needs_clarification'
    review(c)
    with session_factory() as db:
        db.get(Job,'elig').required_skills='Python, SQL, Java'; db.commit()
    assert not c.get('/jobs/elig/requirements').json()['review_current']
    assert c.get('/jobs/elig/eligibility').json()['status']=='needs_clarification'


def test_concurrent_review_and_unresolved_conditions(scenario):
    c=scenario; save_profile(c)
    old=c.get('/jobs/elig/requirements').json()
    assert review(c,unresolved_requirements=['Verify degree requirement']).status_code==200
    assert c.get('/jobs/elig/eligibility').json()['status']=='needs_clarification'
    assert c.put('/jobs/elig/requirements',json={'expected_version':0,'source_hash':old['source_hash'],
        'confirmed':True,'review_note':'Old review','data':old['suggested']['data']}).status_code==409


def test_new_requirement_review_invalidates_resume_approval(scenario):
    c=scenario; save_profile(c); review(c)
    p=c.post('/jobs/elig/resume-proposals',json={'resume_id':'master9'}).json()
    assert c.post('/jobs/elig/resume-proposals/'+p['id']+'/review',json={
        'decision':'approve','content_sha256':p['content_sha256'],'confirmed_truthful':True}).status_code==200
    assert review(c,maximum_notice_days=20).status_code==200
    assert c.get('/jobs/elig/resume-proposals').json()[0]['stale_reason']
    assert c.get('/jobs/elig/resume-proposals/'+p['id']+'/export/pdf').status_code==409


def test_submission_freezes_confirmed_answers(scenario):
    from app.applications import today
    c=scenario; save_profile(c); review(c)
    p=c.post('/jobs/elig/resume-proposals',json={'resume_id':'master9'}).json()
    c.post('/jobs/elig/resume-proposals/'+p['id']+'/review',json={
        'decision':'approve','content_sha256':p['content_sha256'],'confirmed_truthful':True})
    ready=c.put('/jobs/elig/preparation',json={'resume_id':'master9','checklist':{
        'posting_open':True,'location_eligible':True,'documents_ready':True}})
    assert ready.json()['ready'],ready.text
    recorded=c.post('/jobs/elig/application',json={'confirmed_submitted':True,'submitted_on':str(today()),'channel':'Test employer receipt'})
    assert recorded.status_code==201,recorded.text
    snapshot=recorded.json()['preparation']['submission_snapshot']
    assert snapshot['eligibility']['status']=='eligible'
    assert snapshot['confirmed_application_answers']['profile_version']==1
    save_profile(c,experience_years=0)
    assert c.get('/jobs/elig/preparation').json()['preparation']['submission_snapshot']==snapshot
    assert review(c).status_code==409
