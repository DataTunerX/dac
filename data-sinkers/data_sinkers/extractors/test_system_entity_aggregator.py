import unittest

from .base import SystemEntityAggregator


class TestSystemEntityAggregatorEndpointModels(unittest.TestCase):
    def setUp(self) -> None:
        self.aggregator = SystemEntityAggregator()

    def test_dict_request_model_does_not_crash(self) -> None:
        file_data = {
            "file_type": "typescript",
            "analysis_result": {
                "file_summary": "api routes",
                "api_endpoints": [
                    {
                        "method": "POST",
                        "path": "/api/skills",
                        "request": {
                            "name": "CreateSkillRequest",
                            "fields": [{"name": "title", "type": "string"}],
                        },
                        "response": {"name": "CreateSkillResponse"},
                        "business_summary": "create skill",
                    }
                ],
            },
        }

        self.aggregator.add_file_analysis("convex/skills.ts", file_data)

        endpoint = self.aggregator.api_endpoints["POST /api/skills"]
        self.assertIn("CreateSkillRequest", endpoint["request_models"])
        self.assertIn("CreateSkillResponse", endpoint["response_models"])

    def test_list_request_models(self) -> None:
        file_data = {
            "file_type": "typescript",
            "analysis_result": {
                "api_endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/items",
                        "request": ["QueryParams", "AuthHeader"],
                        "response": "ItemListResponse",
                    }
                ],
            },
        }

        self.aggregator.add_file_analysis("routes/items.ts", file_data)
        endpoint = self.aggregator.api_endpoints["GET /api/items"]
        self.assertEqual(
            endpoint["request_models"],
            {"QueryParams", "AuthHeader"},
        )


if __name__ == "__main__":
    unittest.main()
