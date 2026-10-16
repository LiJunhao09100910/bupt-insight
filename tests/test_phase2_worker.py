"""Real local worker / HTTP transport tested only against a fictional loopback server."""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.analysis import api_call, rules
from core.ai_worker import request
from core.errors import InsightError


@pytest.fixture
def server():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body)
            if self.path.startswith('/slow'):
                time.sleep(2)
            data=json.loads(body['messages'][1]['content'])
            value=rules(data['notice']).model_dump()
            out=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}]}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(out)));self.end_headers()
            try:self.wfile.write(out)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    srv=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{srv.server_port}',calls
    srv.shutdown();srv.server_close();thread.join(timeout=3)


def test_actual_subprocess_fake_server_structured_contract(server,monkeypatch):
    monkeypatch.delenv('LLM_API_KEY',raising=False)
    base,calls=server
    data={'notice':{'title':'虚构科研招募','body':'科研报名截止2026年12月20日。'},'profile':{},'truncated':False}
    result=api_call(data,{'base_url':base+'/v1','model':'fictional-test-model'},4)
    assert result['category']=='research' and len(calls)==1
    assert calls[0]['response_format']['json_schema']['strict']
    assert calls[0]['messages'][0]['role']=='system'


def test_slow_subprocess_terminated_within_wall_budget(server):
    base,calls=server;start=time.monotonic()
    with pytest.raises(ValueError):
        api_call({'notice':{'title':'虚构慢请求','body':'虚构正文'}}, {'base_url':base+'/slow','model':'fake'}, .5)
    assert time.monotonic()-start < 1.5


@pytest.mark.parametrize('endpoint',['http://example.test/v1','https://user:password@example.test/v1','https://example.test/v1?token=SECRET','https://example.test/v1#fragment'])
def test_worker_rejects_unsafe_endpoint_before_network(endpoint,monkeypatch):
    def forbidden(*a,**kw):pytest.fail('must not call network')
    monkeypatch.setattr('requests.Session.post',forbidden)
    with pytest.raises(ValueError):request({'options':{'base_url':endpoint,'model':'fake'},'request':{}})


@pytest.mark.parametrize('kind',['invalid_json','refusal','truncated','redirect','oversized'])
def test_worker_provider_failure_never_accepts_bad_output(kind,monkeypatch):
    class Response:
        status_code=302 if kind=='redirect' else 200
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def iter_content(self,*a):
            if kind=='invalid_json':yield b'not json'
            elif kind=='oversized':yield b'x'*100001
            else:yield json.dumps({'choices':[{'finish_reason':'length' if kind=='truncated' else 'stop','message':{'refusal':'refused','content':'{}'}}]}).encode()
    monkeypatch.setattr('requests.Session.post',lambda *a,**kw:Response())
    with pytest.raises(ValueError):request({'options':{'base_url':'http://127.0.0.1:9999/v1','model':'fake'},'request':{}})


def test_fictional_evaluation_fixed_and_all_important_items_recalled():
    from tools.evaluate_analysis import evaluate
    report=evaluate()
    assert report['n']==24 and report['mandatory_n']==7 and report['mandatory_recall']==1
    assert len(report['errors'])==3
    assert report['simulation']
    assert report['human_reviewed_subset']['n']==7
    assert report['human_reviewed_subset']['mandatory_recalled']==2
