from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.models import Job, Resume, ResumeProposal


@pytest.fixture
def proposal_job(client, session_factory):
    with session_factory() as db:
        db.add(Resume(id='master', filename='master.pdf', text='Sample Candidate\nPython SQL Docker\nBuilt a Python API using SQL.\nEducation: Computer Science'))
        db.commit()
    assert client.post('/jobs', json={'job_id':'review', 'company':'Atlan', 'role':'Data Engineer',
        'location':'India', 'required_skills':'Python, SQL, Kafka'}).status_code == 201
    from conftest import confirm_phase9
    confirm_phase9(client, "review")
    return client


def propose(client, **extra):
    response = client.post('/jobs/review/resume-proposals', json={'resume_id':'master', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, proposal, **extra):
    return client.post('/jobs/review/resume-proposals/'+proposal['id']+'/review',json={
        'decision':'approve','content_sha256':proposal['content_sha256'],'confirmed_truthful':True, **extra})


def export_url(proposal, format='pdf'):
    return '/jobs/review/resume-proposals/'+proposal['id']+'/export/'+format


def test_evidence_and_exports_require_explicit_approval(proposal_job, session_factory):
    c=proposal_job; proposal=propose(c)
    assert proposal['status']=='pending'
    assert 'kafka' not in proposal['proposed'].lower()
    assert any(r['requirement']=='kafka' and not r['supported'] for r in proposal['evidence']['requirements'])
    assert c.get(export_url(proposal)).status_code==409
    assert approve(c,proposal,confirmed_truthful=False).status_code==422
    assert approve(c,proposal,content_sha256='0'*64).status_code==409
    with session_factory() as db:
        assert db.get(ResumeProposal,proposal['id']).pdf is None
    result=approve(c,proposal)
    assert result.status_code==200, result.text
    for format in ['pdf','docx']:
        artifact=c.get(export_url(proposal,format))
        assert artifact.status_code==200
        assert sha256(artifact.content).hexdigest()==result.json()[format+'_sha256']
        assert artifact.headers['x-content-sha256']==result.json()[format+'_sha256']
        if format=='pdf':
            assert 'Sample Candidate' in ''.join(p.extract_text() for p in PdfReader(BytesIO(artifact.content)).pages)
        else:
            with ZipFile(BytesIO(artifact.content)) as archive:
                assert 'Sample Candidate' in archive.read('word/document.xml').decode()
    assert approve(c,proposal).status_code==409


def test_new_revision_invalidates_previous_approval_and_rejection_blocks_export(proposal_job):
    c=proposal_job; old=propose(c); assert approve(c,old).status_code==200
    revised=propose(c,edits=[{'before':'Built a Python API using SQL.','after':'Built a SQL-backed Python API.',
        'source_quote':'Built a Python API using SQL.','reason':'Emphasize database integration'}])
    assert revised['status']=='pending'
    assert 'SQL-backed' in revised['diff']
    assert c.get(export_url(old)).status_code==409
    assert approve(c,old).status_code==409
    r=c.post('/jobs/review/resume-proposals/'+revised['id']+'/review',json={
        'decision':'reject','content_sha256':revised['content_sha256']})
    assert r.json()['status']=='rejected'
    assert c.get(export_url(revised)).status_code==409


def test_fabricated_evidence_and_wrong_job_are_rejected(proposal_job):
    c=proposal_job
    response=c.post('/jobs/review/resume-proposals',json={'resume_id':'master','edits':[{
        'before':'Python','after':'Kafka','source_quote':'Built Kafka pipelines','reason':'Match posting'}]})
    assert response.status_code==422
    proposal=propose(c)
    c.post('/jobs',json={'job_id':'other','company':'Atlan','role':'Other'})
    assert c.get('/jobs/other/resume-proposals/'+proposal['id']+'/export/pdf').status_code==404
    assert c.post('/jobs/other/resume-proposals/'+proposal['id']+'/review',json={
        'decision':'approve','content_sha256':proposal['content_sha256'],'confirmed_truthful':True}).status_code==404


@pytest.mark.parametrize('change',['requirements','master_text','master_selection'])
def test_changed_inputs_require_new_review(proposal_job, session_factory, monkeypatch, change):
    c=proposal_job; proposal=propose(c); assert approve(c,proposal).status_code==200
    with session_factory() as db:
        if change=='requirements': db.get(Job,'review').required_skills='Java'
        if change=='master_text': db.get(Resume,'master').text+=' New text'
        db.commit()
    if change=='master_selection': monkeypatch.setenv('MASTER_RESUME_ID','another')
    assert c.get(export_url(proposal)).status_code==409
    assert c.get('/jobs/review/resume-proposals').json()[0]['stale_reason']


def test_submission_gate_and_frozen_artifacts(proposal_job, session_factory):
    c=proposal_job
    c.patch('/jobs/review',json={'status':'Approved','human_approval':True})
    preparation={'resume_id':'master','checklist':{'posting_open':True,'location_eligible':True,'documents_ready':True}}
    assert not c.put('/jobs/review/preparation',json=preparation).json()['ready']
    from app.applications import today
    body={'confirmed_submitted':True,'submitted_on':str(today()),'channel':'Employer site'}
    assert c.post('/jobs/review/application',json=body).status_code==409
    proposal=propose(c); assert approve(c,proposal).status_code==200
    assert c.get('/jobs/review/preparation').json()['ready']
    recorded=c.post('/jobs/review/application',json=body)
    assert recorded.status_code==201, recorded.text
    snapshot=recorded.json()['preparation']['submission_snapshot']
    assert snapshot['resume_proposal_id']==proposal['id']
    assert snapshot['approved_content_sha256']==proposal['content_sha256']
    assert snapshot['pdf_sha256']
    assert c.post('/jobs/review/resume-proposals',json={'resume_id':'master'}).status_code==409
    with session_factory() as db:
        db.get(Job,'review').required_skills='Changed after submission'
        db.commit()
    assert c.get(export_url(proposal)).status_code==200


def test_high_job_score_does_not_approve_resume(proposal_job):
    c=proposal_job
    c.post('/jobs/review/resume-assessment',json={'required_skills':'Python, SQL','resume_id':'master'})
    assert c.get('/dashboard/jobs/review').json()['status']=='Approved'
    proposal=propose(c)
    assert proposal['status']=='pending'
    assert c.get(export_url(proposal)).status_code==409
