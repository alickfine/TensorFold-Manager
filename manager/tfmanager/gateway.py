"""Authenticated HTTP handlers use this real OpenAI proxy and accounting path."""
import http.client
import json
import math
import select
import socket
import threading
import time
from .state import APIError

MAX_RESPONSE=32*1024*1024

def validate_payload(data):
    if not isinstance(data,dict):raise APIError('JSON object required')
    if 'stream' in data and not isinstance(data['stream'],bool):raise APIError('stream must be boolean')
    if 'max_tokens' in data and (isinstance(data['max_tokens'],bool) or not isinstance(data['max_tokens'],int) or not 1<=data['max_tokens']<=2097152):raise APIError('Invalid max_tokens')
    if 'messages' in data and (not isinstance(data['messages'],list) or not data['messages']):raise APIError('messages must be a non-empty array')
    return data

def usage_into(record,payload):
    error=payload.get('error')
    if error:
        record.update(status=502,error=str(error.get('message',error) if isinstance(error,dict) else error))
    usage=payload.get('usage') or {}
    if not isinstance(usage,dict):usage={}
    for source,target in (('prompt_tokens','input_tokens'),('completion_tokens','output_tokens')):
        value=usage.get(source)
        if isinstance(value,int) and not isinstance(value,bool) and value>=0:record[target]=value
    details=usage.get('prompt_tokens_details') or {}
    cached=details.get('cached_tokens') if isinstance(details,dict) else None
    if type(cached) is int and cached>=0:record['cache_tokens']=cached
    runtime=payload.get('tensorfold') or {}
    if not isinstance(runtime,dict):return
    def measured(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0
    for source,target in (('tokens_per_second','decode_tps'),('prefill_seconds','prefill_seconds')):
        value=runtime.get(source)
        if measured(value):record[target]=value
    value=runtime.get('time_to_first_token')
    if record.get('ttft') is None and measured(value):record['ttft']=value;record['ttft_source']='engine_runtime'
    count=record.get('input_tokens');cached=record.get('cache_tokens');seconds=record.get('prefill_seconds')
    if type(count) is int and type(cached) is int and 0<=cached<=count and measured(seconds) and seconds>0:
        record['prefill_tps']=(count-cached)/seconds
        record['prefill_tps_source']='uncached_prompt_tokens/prefill_seconds'

REQUEST_PARAMETERS={'max_tokens','temperature','top_p','top_k','seed','stop','presence_penalty','frequency_penalty','stream','enable_thinking','reasoning_effort','thinking_budget','logprobs'}

def request_metadata(engine,data):
    return engine.request_metadata() | {'parameters':{key:value for key,value in data.items() if key in REQUEST_PARAMETERS}}


def completion(engine,store,data,path='/v1/chat/completions',record=True,observe_stream=False,job=None):
    data=validate_payload(data.copy());data['stream']=observe_stream;data.setdefault('model',engine.status().get('served_name') or engine.status()['model'])
    finished_job=threading.Event()
    start=time.monotonic();metrics={'model':data['model'],'status':502,'error':None,'ttft':None,'prefill_tps':None,'decode_tps':None,'input_tokens':None,'output_tokens':None}
    try:
        with engine.request() as connection:
            metrics.update(request_metadata(engine,data));metrics['model']=data['model']
            try:
                connection.connect();upstream_socket=connection.sock
                if job:
                    job.checkpoint()
                    def watch_job():
                        while not finished_job.wait(.05):
                            if job.cancelled:
                                try:upstream_socket.shutdown(socket.SHUT_RDWR)
                                except OSError:pass
                                return
                    threading.Thread(target=watch_job,daemon=True).start()
                connection.request('POST',path,json.dumps(data).encode(),{'Content-Type':'application/json'})
                response=connection.getresponse();metrics['status']=response.status
                if observe_stream and response.status<400:
                    content=[];finished=False
                    while True:
                        if job:job.checkpoint()
                        line=response.readline(1024*1024+1)
                        if not line:break
                        if len(line)>1024*1024:raise APIError('Oversized SSE event','upstream_error',502)
                        if not line.startswith(b'data:'):continue
                        if line[5:].strip()==b'[DONE]':finished=True;break
                        event=json.loads(line[5:]);usage_into(metrics,event)
                        for choice in event.get('choices',[]):
                            delta=choice.get('delta') or {};text=delta.get('content') or delta.get('reasoning_content') or choice.get('text')
                            if text:
                                if metrics['ttft'] is None:metrics['ttft']=time.monotonic()-start;metrics['ttft_source']='gateway_first_delta'
                                content.append(text)
                    if not finished:raise APIError('Stream ended before completion','incomplete_stream',502)
                    if metrics.get('error'):raise APIError(metrics['error'],'upstream_error',502)
                    return {'choices':[{'message':{'role':'assistant','content':''.join(content)}}]},metrics
                raw=response.read(MAX_RESPONSE+1)
                if len(raw)>MAX_RESPONSE:raise APIError('Upstream response too large','upstream_error',502)
                payload=json.loads(raw)
                if response.status>=400:raise APIError(str(payload.get('error',payload)),'upstream_error',response.status)
                usage_into(metrics,payload)
                if metrics.get('error'):raise APIError(metrics['error'],'upstream_error',502)
                return payload,metrics
            finally:connection.close()
    except Exception as exc:
        metrics['error']=str(exc);metrics['status']=getattr(exc,'status',502)
        if job and job.cancelled:metrics['status']=499;job.checkpoint()
        raise
    finally:
        finished_job.set()
        metrics['elapsed']=time.monotonic()-start
        if record:store.record_request(metrics)


def proxy(handler,app,path,data=None):
    if data is not None:validate_payload(data);data=data.copy();data.setdefault('model',app.engine.status().get('served_name') or app.engine.status()['model'])
    stream=bool(data and data.get('stream'));start=time.monotonic();metrics={'model':data.get('model') if data else app.engine.status()['model'],'status':502,'error':None,'ttft':None}
    began=False;done=threading.Event();disconnected=threading.Event();connection=None
    try:
        with app.engine.request() as connection:
            if data is not None:metrics.update(request_metadata(app.engine,data));metrics['model']=data['model']
            connection.connect();upstream_socket=connection.sock
            def watch_client():
                # A browser Abort closes the upstream socket immediately, including during prefill.
                while not done.wait(.1):
                    try:
                        readable,_,_=select.select([handler.connection],[],[],0)
                        if readable and handler.connection.recv(1,socket.MSG_PEEK)==b'':
                            disconnected.set();upstream_socket.shutdown(socket.SHUT_RDWR);return
                    except OSError:return
            threading.Thread(target=watch_client,daemon=True).start()
            connection.request('POST' if data is not None else 'GET',path,json.dumps(data).encode() if data is not None else None,{'Content-Type':'application/json'})
            response=connection.getresponse();metrics['status']=response.status
            if stream and response.status<400:
                handler.send_response(response.status);handler.send_header('Content-Type','text/event-stream; charset=utf-8');handler.send_header('Cache-Control','no-store');handler.send_header('Connection','close');handler.security_headers();handler.end_headers();handler.close_connection=True;began=True;finished_stream=False
                while True:
                    line=response.readline(1024*1024+1)
                    if not line:break
                    if len(line)>1024*1024:raise APIError('Upstream SSE event exceeds limit','upstream_error',502)
                    if line.startswith(b'data:') and line[5:].strip()==b'[DONE]':finished_stream=True
                    if line.startswith(b'data:') and line[5:].strip()!=b'[DONE]':
                        try:
                            payload=json.loads(line[5:]);usage_into(metrics,payload)
                            choices=payload.get('choices') or []
                            if metrics['ttft'] is None and any((c.get('delta') or {}).get('content') or (c.get('delta') or {}).get('reasoning_content') or c.get('text') for c in choices):metrics['ttft']=time.monotonic()-start;metrics['ttft_source']='gateway_first_delta'
                        except (ValueError,TypeError):pass
                    handler.wfile.write(line);handler.wfile.flush()
                if not finished_stream:raise APIError('Stream ended before completion','incomplete_stream',502)
            else:
                raw=response.read(MAX_RESPONSE+1)
                if len(raw)>MAX_RESPONSE:raise APIError('Upstream response too large','upstream_error',502)
                try:payload=json.loads(raw);usage_into(metrics,payload)
                except ValueError:raise APIError('Upstream did not return JSON','upstream_error',502)
                handler.respond(payload,response.status);began=True
    except (BrokenPipeError,ConnectionResetError) as exc:
        metrics.update(status=499,error='Client cancelled');handler.close_connection=True
    except Exception as exc:
        metrics['error']=str(exc)
        if disconnected.is_set():metrics['status']=499
        elif not began:raise APIError('Upstream request failed: '+str(exc),'upstream_error',502) from exc
        else:metrics['status']=502;handler.close_connection=True
    finally:
        done.set()
        if connection:connection.close()
        metrics['elapsed']=time.monotonic()-start
        if data is not None:app.store.record_request(metrics)
