#!/usr/bin/env python3
"""
Test FMP Historical APIs for survivorship-bias-free backtesting.

Tests:
1. Historical S&P 500 constituent changes
2. Historical market cap data
"""

import asyncio
import json
from data.fmp_client import FMPClient

async def main():
    fmp = FMPClient()

    print("=" * 70)
    print("Testing FMP Historical APIs")
    print("=" * 70)

    # Test 1: Historical S&P 500 Constituents
    print("\n1. Historical S&P 500 Constituent Changes")
    print("-" * 50)

    try:
        changes = await fmp.get_historical_sp500_constituents()
        print(f"   Total changes returned: {len(changes)}")

        if changes:
            print(f"   First change: {changes[0]}")
            print(f"   Last change: {changes[-1]}")

            # Check date range
            dates = [c.get('dateAdded') or c.get('date') or c.get('addedDate') for c in changes if c]
            dates = [d for d in dates if d]
            if dates:
                print(f"   Date range: {min(dates)} to {max(dates)}")

            # Sample a few changes
            print(f"\n   Sample changes:")
            for change in changes[:5]:
                print(f"   {change}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # Test 2: Current S&P 500 Constituents
    print("\n2. Current S&P 500 Constituents")
    print("-" * 50)

    try:
        current = await fmp.get_sp500_constituents()
        print(f"   Current members: {len(current)}")
        if current:
            print(f"   Sample: {current[0]}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # Test 3: Historical Market Cap (using stable API)
    print("\n3. Historical Market Cap (AAPL)")
    print("-" * 50)

    try:
        # Try the stable endpoint
        data = await fmp._request(
            "/historical-market-capitalization",
            params={"symbol": "AAPL"},
            use_stable=True
        )
        print(f"   Data points returned: {len(data) if data else 0}")

        if data:
            print(f"   First record: {data[0]}")
            print(f"   Last record: {data[-1]}")

            # Check date range
            dates = [d.get('date') for d in data if d.get('date')]
            if dates:
                print(f"   Date range: {min(dates)} to {max(dates)}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # Test 4: Historical prices for a delisted stock (test)
    print("\n4. Historical Prices for Delisted Stock Test")
    print("-" * 50)

    # Try a stock that was removed from S&P 500 (e.g., GE was restructured)
    test_tickers = ["GE", "DOW", "CTVA"]  # DOW and CTVA were spun off from DowDuPont

    for ticker in test_tickers:
        try:
            data = await fmp.get_historical_prices(ticker, from_date="2016-01-01", to_date="2016-12-31")
            if data and 'historical' in data:
                hist = data['historical']
                print(f"   {ticker}: {len(hist)} days of data from 2016")
            else:
                print(f"   {ticker}: No historical data")
        except Exception as e:
            print(f"   {ticker}: ERROR - {e}")

    await fmp.close()

    print("\n" + "=" * 70)
    print("Test complete")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
