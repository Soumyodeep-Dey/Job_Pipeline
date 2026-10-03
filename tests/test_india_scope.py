def test_india_scope_filters_before_pagination(client):
    for identifier, location, status in [('a','New York','New'),('b','Bengaluru','New'),
                                          ('c','India','Rejected'),('d','Remote','New'),
                                          ('e','Remote - India','New'),('f','Indiana','New')]:
        assert client.post('/jobs', json={'job_id':identifier,'company':'Atlan','role':'Developer',
                                         'location':location,'status':status}).status_code == 201
    assert [j['job_id'] for j in client.get('/jobs?scope=india&limit=1&offset=1').json()] == ['e']
    assert {j['job_id'] for j in client.get('/jobs?scope=history').json()} == {'a','c','d','f'}
    assert len(client.get('/jobs').json()) == 6


def test_profile_rejects_documentation_placeholders(client):
    assert client.put('/matching-profile', json={'locations':['string']}).status_code == 422
    assert client.put('/matching-profile', json={'demonstrated_skills':['string']}).status_code == 422
    assert client.put('/matching-profile', json={}).status_code == 200
    assert 'India' in client.get('/matching-profile').json()['locations']
