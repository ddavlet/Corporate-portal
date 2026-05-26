def list_results(response):
    data = response.data
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data
