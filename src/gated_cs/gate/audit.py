import hashlib, json

class AuditLog:
    def __init__(self, path):
        self.path = path
    def record(self, entry):
        payload = json.dumps(entry, sort_keys=True)
        eid = hashlib.sha256(payload.encode()).hexdigest()[:16]
        entry = {"id": eid, **entry}
        with open(self.path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return eid
    def entries(self):
        try:
            with open(self.path) as f:
                return [json.loads(l) for l in f if l.strip()]
        except FileNotFoundError:
            return []
