"""Explicit reference-answer tests. Text agreement is not knowledge accuracy."""
import time
import uuid
from .state import APIError, bounded_number, identifier, redact
from .gateway import completion

class Accuracy:
    def __init__(self, store, jobs, engine):
        self.store, self.jobs, self.engine = store, jobs, engine
        jobs.register('accuracy', self.run)
    def status(self):
        return {'cases': self.store.all('accuracy_case'), 'results': self.store.all('accuracy_result'),
                'scoring': 'reference_text_agreement', 'description': 'Exact or substring agreement with user-provided reference; not general model accuracy.'}
    def add(self, data):
        if not isinstance(data, dict) or set(data) - {'id','name','prompt','expected','match','max_tokens'}:
            raise APIError('Unsupported reference test field')
        for field in ('prompt', 'expected'):
            if not isinstance(data.get(field), str) or not 1 <= len(data[field]) <= 65536:
                raise APIError('Non-empty prompt and reference answer required')
        name = data.get('name', 'Reference test')
        if not isinstance(name, str) or not 1 <= len(name) <= 120: raise APIError('Invalid test name')
        match = data.get('match', 'exact')
        if match not in ('exact', 'contains'): raise APIError('Only exact or contains text scoring is supported')
        tokens = bounded_number(data.get('max_tokens', 256), 1, 32768, 'max_tokens', True)
        case_id = identifier(data.get('id', uuid.uuid4().hex))
        case = dict(id=case_id, name=name, prompt=data['prompt'], expected=data['expected'], match=match, max_tokens=tokens)
        return self.store.put('accuracy_case', case, case_id)
    def remove(self, case_id):
        self.store.delete('accuracy_case', identifier(case_id)); return self.status()
    def reset(self, data):
        if data.get('confirm') is not True: raise APIError('Explicit result reset confirmation required')
        if any(row['kind']=='accuracy' and row['status'] in ('running','queued','paused') for row in self.jobs.list()):
            raise APIError('Stop the active reference test before resetting results', 'busy', 409)
        for result in self.store.all('accuracy_result'): self.store.delete('accuracy_result', result['id'])
        return self.status()
    def start(self, data):
        cases = self.store.all('accuracy_case')
        selected = data.get('case_ids')
        if selected is not None:
            if not isinstance(selected, list) or any(not isinstance(item,str) for item in selected): raise APIError('Invalid selected cases')
            if set(selected) - {case['id'] for case in cases}: raise APIError('Unknown reference test')
            cases = [case for case in cases if case['id'] in selected]
        if not cases: raise APIError('Add an explicit reference test first', 'reference_required', 409)
        if len(cases)>200: raise APIError('At most 200 reference tests per run')
        return self.jobs.create('accuracy', {'cases': cases})
    def run(self, job):
        snapshot = self.engine.request_metadata()
        result = dict(id=job.id, created_at=time.time(), status='running', scoring='reference_text_agreement',
                      model=snapshot['model'], engine_version=snapshot['engine_version'], runtime=snapshot,
                      results=[], passed=0, total=len(job.params['cases']), completed=0, agreement_rate=None)
        self.store.put('accuracy_result', result, job.id)
        try:
            for index, case in enumerate(job.params['cases']):
                job.checkpoint()
                if self.engine.request_metadata()['engine_started_at'] != snapshot['engine_started_at']:
                    raise APIError('Engine changed during reference tests', 'engine_changed', 409)
                job.progress(case=index+1, total=result['total'], name=case['name'])
                payload, metrics = completion(self.engine, self.store, {'model':snapshot['model'],
                    'messages':[{'role':'user','content':case['prompt']}], 'max_tokens':case['max_tokens'],
                    'temperature':0, 'enable_thinking':False}, job=job)
                choices = payload.get('choices')
                if not isinstance(choices,list) or not choices: raise APIError('Missing generated answer', 'upstream_error', 502)
                output = choices[0].get('message',{}).get('content')
                if not isinstance(output,str): raise APIError('Missing answer text', 'upstream_error', 502)
                passed = output == case['expected'] if case['match']=='exact' else case['expected'] in output
                result['results'].append(dict(case_id=case['id'], case=case, output=output, passed=passed, metrics=metrics))
                result['passed'] += int(passed); result['completed'] += 1
                result['agreement_rate'] = result['passed']/result['completed']
                self.store.put('accuracy_result', result, job.id)
            result['status']='completed'; return result
        except Exception as exc:
            result.update(status='cancelled' if job.cancelled else 'failed', error=redact(exc)); raise
        finally: self.store.put('accuracy_result', result, job.id)
