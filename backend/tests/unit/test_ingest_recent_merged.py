from __future__ import annotations


class FakeRecentMergedClient:
    def __init__(self, total: int = 150, page_size: int = 100) -> None:
        self.total = total
        self.page_size = page_size
        self.requested_first: list[int] = []

    def query(self, document: str, variables: dict) -> dict:
        first = int(variables["first"])
        assert first <= 100, f"GitHub allows at most 100 records per connection, got {first}"
        self.requested_first.append(first)
        after = variables.get("after")
        offset = int(after) if after is not None else 0
        batch_end = min(offset + first, self.total)
        numbers = list(range(offset + 1, batch_end + 1))
        has_next = batch_end < self.total
        next_cursor = str(batch_end) if has_next else None
        return {
            "data": {
                "repository": {
                    "pullRequests": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": next_cursor},
                        "nodes": [{"number": n} for n in numbers],
                    }
                }
            }
        }


def test_recent_merged_numbers_caps_each_page_at_one_hundred() -> None:
    from app.services.ingest.pipeline import recent_merged_numbers

    client = FakeRecentMergedClient(total=150)
    numbers = recent_merged_numbers(client, "urllib3", "urllib3", 150)
    assert numbers == list(range(1, 151))
    assert all(size <= 100 for size in client.requested_first)
    assert client.requested_first == [100, 50]


def test_recent_merged_numbers_stops_short_of_the_bound() -> None:
    from app.services.ingest.pipeline import recent_merged_numbers

    client = FakeRecentMergedClient(total=40)
    numbers = recent_merged_numbers(client, "urllib3", "urllib3", 150)
    assert numbers == list(range(1, 41))
    assert client.requested_first == [100]
