from copy import deepcopy


class FakeFirestoreClient:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict]] = {}

    def collection(self, name: str):
        return FakeFirestoreCollection(self.data.setdefault(name, {}))


class FakeFirestoreCollection:
    def __init__(self, documents: dict[str, dict]) -> None:
        self.documents = documents

    def document(self, document_id: str):
        return FakeFirestoreDocument(self.documents, document_id)

    def stream(self):
        return [
            FakeFirestoreSnapshot(True, value)
            for value in self.documents.values()
        ]


class FakeFirestoreDocument:
    def __init__(self, documents: dict[str, dict], document_id: str) -> None:
        self.documents = documents
        self.document_id = document_id

    def set(self, value: dict) -> None:
        self.documents[self.document_id] = deepcopy(value)

    def get(self):
        exists = self.document_id in self.documents
        return FakeFirestoreSnapshot(exists, self.documents.get(self.document_id, {}))


class FakeFirestoreSnapshot:
    def __init__(self, exists: bool, value: dict) -> None:
        self.exists = exists
        self.value = deepcopy(value)

    def to_dict(self) -> dict:
        return deepcopy(self.value)
