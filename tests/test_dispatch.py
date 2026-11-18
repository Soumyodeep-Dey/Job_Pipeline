from types import SimpleNamespace
from hashlib import sha256

import pytest

from app.dispatch import destination
from app.hosted_forms import fill_and_send, form_url
from app.models import (ApplicantProfile, DispatchAttempt, Job, JobEvidence, DiscoveryRun,
                        ApplicationPreparation)
from app.sender import consider, process, recover
from test_applications import prepared

URL = "https://jobs.ashbyhq.com/atlan/12345678-1234-1234-1234-123456789abc"

def test_destination_requires_exact_discovered_tenant():
    ev=SimpleNamespace(provider="ashby",board_url="https://jobs.ashbyhq.com/atlan")
    for url in [URL.replace("atlan","other"),URL.replace(".com/",".com.evil/"),URL.replace("https:","http:")]:
        assert destination(SimpleNamespace(source_url=url),ev) is None

@pytest.fixture
def ready(client,session_factory,prepared,monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr('app.sender.now', lambda: datetime(2026,11,18,4,0,tzinfo=timezone.utc))
    from test_applications import approve_resume
    client.put('/matching-profile',json={'target_roles':['Developer']}).raise_for_status()
    with session_factory() as db:
        job=db.get(Job,'apply')
        job.source_url=URL
        db.add(DiscoveryRun(id='dispatch-run',status='completed',profile_snapshot={},results=[]))
        db.flush()
        db.add(JobEvidence(job_id='apply',run_id='dispatch-run',provider='ashby',
            board_url='https://jobs.ashbyhq.com/atlan',career_page='https://example.com/careers',
            description='',explanation={}))
        p=db.get(ApplicantProfile,1)
        p.data={**p.data,'email':'test@example.org'}
        db.commit()
    approve_resume(client)
    client.put('/dispatch',json={'enabled':True}).raise_for_status()
    return session_factory

@pytest.mark.parametrize("outcome",["receipt","uncertain","blocked","paused"])
def test_dispatch_once(client,ready,outcome):
    with ready() as db:
        assert consider(db,db.get(Job,'apply'))=='apply'
        clicks=[]
        def transport(snapshot, facts, pdf, before_submit):
            assert sha256(pdf).hexdigest()==snapshot['pdf_sha256']
            if outcome=='blocked':
                raise ValueError('Unsupported form')
            if outcome=='paused':
                client.put('/dispatch',json={'enabled':False}).raise_for_status()
            before_submit()
            clicks.append(1)
            if outcome=='uncertain':
                raise TimeoutError()
            return 'Your application was successfully submitted.'
        process(db,'apply',transport,lambda *args:None)
        recover(db)
        assert consider(db,db.get(Job,'apply')) is None
        row=db.get(DispatchAttempt,'apply')
        if outcome=='receipt':
            assert row.state=='confirmed' and db.get(Job,'apply').status=='Applied'
            assert db.get(ApplicationPreparation,'apply').submission_snapshot['receipt']==row.message
        elif outcome=='uncertain':
            assert row.state=='uncertain' and len(clicks)==1
            assert client.post('/jobs/apply/dispatch/recheck').status_code==409
        else:
            assert row.state=='needs_review' and not clicks

def test_browser_fixture():
    playwright=pytest.importorskip("playwright.sync_api")
    html="""<h1>Data Engineer</h1><form>
    <label>Name<input required></label><label>Email<input type="email" required></label>
    <label>Resume<input type="file" required></label>
    <button type="button" onclick="this.form.outerHTML='<p>Your application was successfully submitted.</p>'">Submit Application</button></form>"""
    with playwright.sync_playwright() as engine:
        browser=engine.chromium.launch(executable_path="/usr/bin/chromium")
        page=browser.new_page()
        page.route("**/*",lambda route:route.fulfill(body=html,content_type="text/html"))
        stamp=[]
        pdf=b"synthetic bytes"
        receipt=fill_and_send(page,{'role':'Data Engineer','url':URL,'pdf_sha256':sha256(pdf).hexdigest()},
            {'full_name':'Fixture','email':'test@example.org'},pdf,lambda:stamp.append(1))
        assert receipt=='Your application was successfully submitted.' and stamp==[1]
        browser.close()
