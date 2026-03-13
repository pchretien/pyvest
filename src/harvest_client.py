"""Harvest API client for fetching time entries."""

import requests
import json

from config import HARVEST_API_MAX_PER_PAGE


def get_time_entries(account_id, access_token, harvest_url, from_date, to_date, days_back=None):
    """Fetch all time entries from the Harvest API for a given date range.

    Iterates through all pages of results until the last page is reached.

    Args:
        account_id (str): Harvest account identifier.
        access_token (str): Harvest API bearer token.
        harvest_url (str): Base URL for the Harvest time-entries endpoint.
        from_date (str): Start date in YYYY-MM-DD format.
        to_date (str): End date in YYYY-MM-DD format.
        days_back (int, optional): Number of days back, used only for display.

    Returns:
        list: All time entry dicts returned by the API.

    Raises:
        RuntimeError: On timeout, HTTP error, or invalid JSON response.
    """
    if days_back:
        print(f"Fetching time entries from {from_date} to {to_date} (last {days_back} days)...")
    else:
        print(f"Fetching time entries from {from_date} to {to_date}...")

    url = harvest_url
    all_entries = []
    page = 1

    headers = {
        "Harvest-Account-ID": account_id,
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "Python Harvest Script"
    }

    params = {
        "from": from_date,
        "to": to_date,
        "page": page,
        "per_page": HARVEST_API_MAX_PER_PAGE
    }

    try:
        while True:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Harvest API response is not valid JSON. "
                    f"Status code: {response.status_code}, URL: {url}"
                ) from e

            time_entries = data.get('time_entries', [])

            if not time_entries:
                break

            all_entries.extend(time_entries)

            # Stop when we have consumed the last page
            total_pages = data.get('total_pages', 1)
            if page >= total_pages:
                break

            page += 1
            params['page'] = page

        print(f"Total: {len(all_entries)} entries fetched across {page} page(s)")
        return all_entries

    except requests.exceptions.Timeout as e:
        raise RuntimeError(
            f"Timeout on Harvest API request (URL: {url}). "
            f"Request took more than 30 seconds."
        ) from e
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response else "unknown"
        raise RuntimeError(
            f"HTTP {status_code} error on Harvest API request (URL: {url}). "
            f"Check your credentials and API URL."
        ) from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Error on Harvest API request (URL: {url}): {e}"
        ) from e
