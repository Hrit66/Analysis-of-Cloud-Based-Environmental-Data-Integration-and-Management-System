"""Dataset listing must compare the user's ObjectId as a string."""
from bson import ObjectId
from fastapi.testclient import TestClient

from app.api.auth import get_optional_user
from app.api.datasets import get_database
from app.main import app


class Cursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def skip(self, value):
        return self

    def limit(self, value):
        return self

    async def to_list(self, length=None):
        return self.docs


def _matches(doc, query):
    for key, value in query.items():
        if key == "$or":
            if not any(_matches(doc, clause) for clause in value):
                return False
        elif key == "$and":
            if not all(_matches(doc, clause) for clause in value):
                return False
        elif isinstance(value, dict) and "$in" in value:
            if doc.get(key) not in value["$in"]:
                return False
        elif isinstance(value, dict) and "$exists" in value:
            if (key in doc) != value["$exists"]:
                return False
        elif doc.get(key) != value:
            return False
    return True


class Collection:
    def __init__(self, docs):
        self.docs = docs

    def _matching(self, query):
        return [doc for doc in self.docs if _matches(doc, query)]

    async def count_documents(self, query):
        return len(self._matching(query))

    def find(self, query):
        return Cursor(self._matching(query))


class Database:
    def __init__(self, docs):
        self.datasets = Collection(docs)


class User:
    def __init__(self, value):
        self.id = ObjectId(value)


def test_listing_compares_string_owner_id():
    owner = "6ad4413353bcebcb5467a7d9"
    other = "6ad4413353bcebcb5467a7d8"
    database = Database([
        {"_id": ObjectId(), "user_id": owner, "filename": "mine.csv", "status": "completed"},
        {"_id": ObjectId(), "user_id": other, "filename": "theirs.csv", "status": "completed"},
    ])
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_optional_user] = lambda: User(owner)
    try:
        response = TestClient(app).get("/api/datasets")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["filename"] for item in body["items"]] == ["mine.csv"]
