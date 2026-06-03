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

    def where(self, field_path: str, op_string: str, value):
        return FakeFirestoreQuery(self.documents).where(field_path, op_string, value)

    def stream(self):
        return [
            FakeFirestoreSnapshot(True, value)
            for value in self.documents.values()
        ]


class FakeFirestoreQuery:
    def __init__(self, documents: dict[str, dict]) -> None:
        self.documents = documents
        self.filters: list[tuple[str, str, object]] = []

    def where(self, field_path: str, op_string: str, value):
        query = FakeFirestoreQuery(self.documents)
        query.filters = [*self.filters, (field_path, op_string, value)]
        return query

    def stream(self):
        return [
            FakeFirestoreSnapshot(True, value)
            for value in self.documents.values()
            if all(_matches_filter(value, field_path, op_string, expected) for field_path, op_string, expected in self.filters)
        ]


def _matches_filter(
    document: dict,
    field_path: str,
    op_string: str,
    expected: object,
) -> bool:
    if op_string != "==":
        return False
    current = document
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current == expected


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
