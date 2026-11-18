import json
from datetime import datetime, timezone
from app.discovery.sources import board_from_url, fetch_jobs, SourceError
from app.models import DiscoveryRun
import pytest

class Fake:
    def __init__(self, fail=False): self.urls=[]; self.fail=fail
    def get(self,url,hosts,public_api=False):
        self.urls.append(url)
        assert hosts == {'api.smartrecruiters.com'} and public_api
        if '?' in url: data={'content':[{'id':'123'}], 'totalFound':11}
        else:
            if self.fail: raise SourceError('HTTP 403')
            data={'name':'Data Engineer','postingUrl':'https://jobs.smartrecruiters.com/Example/123',
                  'location':{'city':'Bengaluru','country':'in'},
                  'jobAd':{'sections':{'jobDescription':{'text':'<p>Python and SQL</p>'}}}}
        return url,json.dumps(data).encode()

def test_smart_public_details_pagination():
    board=board_from_url('https://careers.smartrecruiters.com/Example')
    assert board.provider=='smartrecruiters'
    f=Fake();jobs,errors,truncated=fetch_jobs(board,f,100,5)
    assert 'limit=10&offset=5' in f.urls[0] and 'destination=PUBLIC' in f.urls[0]
    assert jobs[0]['location']=='Bengaluru; ; India'
    assert jobs[0]['description']=='Python and SQL'
    assert truncated and not errors
    assert board_from_url('https://jobs.smartrecruiters.com.evil.test/Example') is None
    assert board_from_url('https://user:secret@jobs.smartrecruiters.com/Example') is None

def test_detail_failure_does_not_invent_job():
    jobs,errors,truncated=fetch_jobs(board_from_url('https://jobs.smartrecruiters.com/Example'),Fake(True),10)
    assert not jobs and errors and truncated

def test_diagnostics_latest_and_no_mutation(client,session_factory):
    client.post('/jobs',json={'job_id':'india','company':'Atlan','role':'AI Engineer','location':'India'})
    client.post('/jobs',json={'job_id':'remote','company':'Atlan','role':'AI Engineer','location':'Remote'})
    with session_factory() as db:
        db.add(DiscoveryRun(id='old',status='failed',started_at=datetime(2026,1,1,tzinfo=timezone.utc),profile_snapshot={},results=[{'company_id':1,'status':'failed','errors':['robots blocked']}]))
        db.add(DiscoveryRun(id='new',status='completed',started_at=datetime(2026,2,1,tzinfo=timezone.utc),profile_snapshot={},results=[{'company_id':1,'status':'completed','errors':[]}]))
        db.commit()
    before=client.get('/jobs').json()
    report=client.get('/discovery/diagnostics').json()
    assert report['funnel']['stored_jobs']==2
    assert report['funnel']['india_visible']==1
    assert report['companies'][0]['latest']['run_id']=='new'
    assert client.get('/jobs').json()==before


def test_diagnostics_restriction_and_target_funnel(client,session_factory):
    from app.models import Company
    client.put('/matching-profile',json={'target_roles':['AI Engineer']})
    for identifier,role,location in [('a','AI Engineer','India'),('b','Backend Engineer','India'),('c','AI Engineer','Indiana')]:
        assert client.post('/jobs',json={'job_id':identifier,'company':'Atlan','role':role,'location':location}).status_code==201
    with session_factory() as db:
        db.get(Company,1).career_pages=['https://example.com/careers']
        db.add(DiscoveryRun(id='restricted',status='failed',profile_snapshot={},results=[{'company_id':1,'status':'failed','errors':['No supported board'], 'source_attempts':[{'message':'Source disallows URL in robots.txt'}]}]))
        db.commit()
    result=client.get('/discovery/diagnostics').json()
    assert result['companies'][0]['category']=='access_restricted'
    assert result['funnel']['india_visible']==2 and result['funnel']['india_target_visible']==1


def test_smart_empty_page_does_not_loop():
    class Empty:
        def get(self,*args,**kwargs):return '',b'{"content":[],"totalFound":10}'
    with pytest.raises(SourceError):fetch_jobs(board_from_url('https://careers.smartrecruiters.com/Example'),Empty(),10)
