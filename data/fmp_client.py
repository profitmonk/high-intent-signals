"""
Financial Modeling Prep (FMP) API Client.
Primary data source for company financials, SEC filings, and market data.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import json
from pathlib import Path

import httpx
from ratelimit import limits, sleep_and_retry
import backoff

from config.settings import get_settings, Settings


class FMPError(Exception):
    """FMP API error."""
    pass


class FMPRateLimitError(FMPError):
    """Rate limit exceeded."""
    pass


class FMPClient:
    """
    Async client for the Financial Modeling Prep API.

    Provides access to:
    - Company profiles and financials
    - SEC filings (10-K, 10-Q, 8-K)
    - Earnings call transcripts
    - Stock prices and historical data
    - Analyst estimates and recommendations
    - Insider trading data
    - Institutional holdings
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        settings: Optional[Settings] = None,
        cache_enabled: bool = True,
    ):
        """
        Initialize FMP client.

        Args:
            api_key: FMP API key. If None, loads from settings.
            settings: Application settings.
            cache_enabled: Enable disk caching of responses.
        """
        self.settings = settings or get_settings()
        self.api_key = api_key or self.settings.fmp_api_key
        self.base_url = self.settings.fmp_base_url
        self.base_url_v4 = self.settings.fmp_base_url_v4
        self.base_url_stable = self.settings.fmp_base_url_stable
        self.cache_enabled = cache_enabled
        self.cache_dir = self.settings.cache_dir

        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_cache_path(self, endpoint: str, params: Dict[str, Any]) -> Path:
        """Get cache file path for a request."""
        # Create a cache key from endpoint and params
        param_str = "_".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey")
        cache_key = f"{endpoint.replace('/', '_')}_{param_str}.json"
        return self.cache_dir / cache_key

    def _is_cache_valid(self, cache_path: Path, max_age_hours: int = 24) -> bool:
        """Check if cache file is still valid."""
        if not cache_path.exists():
            return False

        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        return datetime.now() - mtime < timedelta(hours=max_age_hours)

    def _read_cache(self, cache_path: Path) -> Optional[Any]:
        """Read data from cache."""
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _write_cache(self, cache_path: Path, data: Any) -> None:
        """Write data to cache."""
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(data, f)
        except IOError:
            pass  # Silently fail cache writes

    @backoff.on_exception(
        backoff.expo,
        (httpx.HTTPStatusError, httpx.ConnectError),
        max_tries=3,
    )
    async def _request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        use_v4: bool = False,
        use_stable: bool = False,
        cache_hours: int = 24,
    ) -> Any:
        """
        Make an API request.

        Args:
            endpoint: API endpoint (e.g., "/profile/AAPL")
            params: Query parameters
            use_v4: Use v4 API base URL
            use_stable: Use stable API base URL (for newer endpoints like DCF)
            cache_hours: Cache validity in hours (0 to disable)

        Returns:
            API response data
        """
        params = params or {}
        params["apikey"] = self.api_key

        if use_stable:
            base = self.base_url_stable
        elif use_v4:
            base = self.base_url_v4
        else:
            base = self.base_url
        url = f"{base}{endpoint}"

        # Check cache
        if self.cache_enabled and cache_hours > 0:
            cache_path = self._get_cache_path(endpoint, params)
            if self._is_cache_valid(cache_path, cache_hours):
                cached_data = self._read_cache(cache_path)
                if cached_data is not None:
                    return cached_data

        # Make request
        client = await self._get_client()
        response = await client.get(url, params=params)

        if response.status_code == 429:
            raise FMPRateLimitError("Rate limit exceeded")

        response.raise_for_status()
        data = response.json()

        # Write to cache
        if self.cache_enabled and cache_hours > 0:
            self._write_cache(cache_path, data)

        return data

    # =========================================================================
    # Company Information
    # =========================================================================

    async def get_company_profile(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get company profile.

        Returns:
            Company profile including sector, industry, description, market cap, etc.
        """
        data = await self._request(f"/profile/{ticker}")
        return data[0] if data else None

    async def get_key_executives(self, ticker: str) -> List[Dict[str, Any]]:
        """Get key executives."""
        return await self._request(f"/key-executives/{ticker}")

    async def get_company_outlook(self, ticker: str) -> Dict[str, Any]:
        """Get comprehensive company outlook."""
        return await self._request(f"/company-outlook", params={"symbol": ticker}, use_v4=True)

    # =========================================================================
    # Financial Statements
    # =========================================================================

    async def get_income_statement(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Get income statements.

        Args:
            ticker: Stock ticker
            period: "annual" or "quarter"
            limit: Number of periods

        Returns:
            List of income statements
        """
        return await self._request(
            f"/income-statement/{ticker}",
            params={"period": period, "limit": limit},
        )

    async def get_balance_sheet(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get balance sheets."""
        return await self._request(
            f"/balance-sheet-statement/{ticker}",
            params={"period": period, "limit": limit},
        )

    async def get_cash_flow(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get cash flow statements."""
        return await self._request(
            f"/cash-flow-statement/{ticker}",
            params={"period": period, "limit": limit},
        )

    async def get_financial_statements(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all financial statements.

        Returns:
            Dictionary with income_statement, balance_sheet, cash_flow
        """
        income, balance, cash = await asyncio.gather(
            self.get_income_statement(ticker, period, limit),
            self.get_balance_sheet(ticker, period, limit),
            self.get_cash_flow(ticker, period, limit),
        )

        return {
            "income_statement": income,
            "balance_sheet": balance,
            "cash_flow": cash,
        }

    # =========================================================================
    # Ratios and Metrics
    # =========================================================================

    async def get_ratios(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get financial ratios."""
        return await self._request(
            f"/ratios/{ticker}",
            params={"period": period, "limit": limit},
        )

    async def get_key_metrics(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get key metrics."""
        return await self._request(
            f"/key-metrics/{ticker}",
            params={"period": period, "limit": limit},
        )

    async def get_financial_growth(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get financial growth metrics."""
        return await self._request(
            f"/financial-growth/{ticker}",
            params={"period": period, "limit": limit},
        )

    async def get_key_metrics_ttm(self, ticker: str) -> Dict[str, Any]:
        """Get trailing twelve months key metrics."""
        data = await self._request(f"/key-metrics-ttm/{ticker}")
        return data[0] if data else {}

    async def get_ratios_ttm(self, ticker: str) -> Dict[str, Any]:
        """Get trailing twelve months ratios."""
        data = await self._request(f"/ratios-ttm/{ticker}")
        return data[0] if data else {}

    # =========================================================================
    # Relative Valuation (Peer & Sector Comparison)
    # =========================================================================

    async def get_sector_pe(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get P/E ratios by sector."""
        params = {}
        if date:
            params["date"] = date
        return await self._request("/sector_price_earning_ratio", params=params, use_v4=True)

    async def get_industry_pe(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get P/E ratios by industry."""
        params = {}
        if date:
            params["date"] = date
        return await self._request("/industry_price_earning_ratio", params=params, use_v4=True)

    async def get_peer_ratios(self, peers: List[str]) -> List[Dict[str, Any]]:
        """Get key ratios for a list of peer companies."""
        if not peers:
            return []
        # Fetch ratios for all peers in parallel
        tasks = [self.get_ratios_ttm(peer) for peer in peers[:10]]  # Limit to 10 peers
        results = await asyncio.gather(*tasks, return_exceptions=True)

        peer_data = []
        for i, result in enumerate(results):
            if not isinstance(result, Exception) and result:
                result["symbol"] = peers[i]
                peer_data.append(result)
        return peer_data

    async def get_dcf_simple(self, ticker: str) -> Dict[str, Any]:
        """Get basic DCF valuation (used as one data point, not primary signal)."""
        data = await self._request(
            f"/discounted-cash-flow",
            params={"symbol": ticker},
            use_stable=True,
        )
        return data[0] if data else {}

    async def get_relative_valuation(self, ticker: str) -> Dict[str, Any]:
        """
        Get relative valuation comparing stock to peers and sector.

        Primary signal: Peer multiples comparison (what the market uses).
        Secondary: DCF premium/discount (one data point, not the signal).
        """
        # Fetch all required data in parallel
        (
            company_ratios,
            company_profile,
            peers_list,
            sector_pe_data,
            industry_pe_data,
            quote,
            dcf_data,
        ) = await asyncio.gather(
            self.get_ratios_ttm(ticker),
            self.get_company_profile(ticker),
            self.get_stock_peers(ticker),
            self.get_sector_pe(),
            self.get_industry_pe(),
            self.get_quote(ticker),
            self.get_dcf_simple(ticker),
            return_exceptions=True,
        )

        # Handle exceptions
        company_ratios = company_ratios if not isinstance(company_ratios, Exception) else {}
        company_profile = company_profile if not isinstance(company_profile, Exception) else {}
        peers_list = peers_list if not isinstance(peers_list, Exception) else []
        sector_pe_data = sector_pe_data if not isinstance(sector_pe_data, Exception) else []
        industry_pe_data = industry_pe_data if not isinstance(industry_pe_data, Exception) else []
        quote = quote if not isinstance(quote, Exception) else {}
        dcf_data = dcf_data if not isinstance(dcf_data, Exception) else {}

        # Get peer ratios and DCF for peers
        peers_to_analyze = peers_list[:8]
        peer_ratios = await self.get_peer_ratios(peers_to_analyze)

        # Fetch DCF for peers in parallel
        peer_dcf_tasks = [self.get_dcf_simple(peer) for peer in peers_to_analyze]
        peer_dcf_results = await asyncio.gather(*peer_dcf_tasks, return_exceptions=True)

        # Extract company multiples
        company_multiples = {
            "pe": company_ratios.get("peRatioTTM", 0),
            "ev_ebitda": company_ratios.get("enterpriseValueMultipleTTM", 0),
            "ps": company_ratios.get("priceToSalesRatioTTM", 0),
            "pb": company_ratios.get("priceToBookRatioTTM", 0),
            "peg": company_ratios.get("pegRatioTTM", 0),
            "pfcf": company_ratios.get("priceToFreeCashFlowsRatioTTM", 0),
        }

        # Calculate peer averages
        def safe_avg(values):
            valid = [v for v in values if v and v > 0 and v < 1000]  # Filter outliers
            return sum(valid) / len(valid) if valid else None

        peer_multiples = {
            "pe": safe_avg([p.get("peRatioTTM", 0) for p in peer_ratios]),
            "ev_ebitda": safe_avg([p.get("enterpriseValueMultipleTTM", 0) for p in peer_ratios]),
            "ps": safe_avg([p.get("priceToSalesRatioTTM", 0) for p in peer_ratios]),
            "pb": safe_avg([p.get("priceToBookRatioTTM", 0) for p in peer_ratios]),
        }

        # Get sector/industry P/E
        sector = company_profile.get("sector", "")
        industry = company_profile.get("industry", "")

        sector_pe = None
        for s in sector_pe_data:
            if s.get("sector", "").lower() == sector.lower():
                sector_pe = s.get("pe")
                break

        industry_pe = None
        for i in industry_pe_data:
            if i.get("industry", "").lower() == industry.lower():
                industry_pe = i.get("pe")
                break

        # Calculate premium/discount vs peers
        def calc_premium(company_val, peer_val):
            if company_val and peer_val and peer_val > 0:
                return ((company_val - peer_val) / peer_val) * 100
            return None

        pe_vs_peers = calc_premium(company_multiples["pe"], peer_multiples["pe"])
        ev_ebitda_vs_peers = calc_premium(company_multiples["ev_ebitda"], peer_multiples["ev_ebitda"])
        ps_vs_peers = calc_premium(company_multiples["ps"], peer_multiples["ps"])
        pe_vs_sector = calc_premium(company_multiples["pe"], sector_pe)

        # Determine valuation signal based on relative metrics
        premiums = [p for p in [pe_vs_peers, ev_ebitda_vs_peers, ps_vs_peers] if p is not None]
        avg_premium = sum(premiums) / len(premiums) if premiums else None

        if avg_premium is not None:
            if avg_premium < -30:
                signal = "SIGNIFICANTLY CHEAPER THAN PEERS"
            elif avg_premium < -15:
                signal = "CHEAPER THAN PEERS"
            elif avg_premium < 15:
                signal = "IN-LINE WITH PEERS"
            elif avg_premium < 30:
                signal = "PREMIUM TO PEERS"
            else:
                signal = "SIGNIFICANT PREMIUM TO PEERS"
        else:
            signal = "INSUFFICIENT DATA"

        # Build peer comparison table with DCF
        peer_comparison = []
        for i, p in enumerate(peer_ratios):
            peer_dcf = peer_dcf_results[i] if i < len(peer_dcf_results) and not isinstance(peer_dcf_results[i], Exception) else {}
            peer_price = peer_dcf.get("Stock Price", 0) or peer_dcf.get("stockPrice", 0)
            peer_dcf_value = peer_dcf.get("dcf", 0)
            peer_dcf_premium = None
            if peer_price and peer_dcf_value:
                peer_dcf_premium = round(((peer_price - peer_dcf_value) / peer_dcf_value) * 100, 1)

            peer_comparison.append({
                "symbol": p.get("symbol", ""),
                "pe": round(p.get("peRatioTTM", 0), 1) if p.get("peRatioTTM") else None,
                "ev_ebitda": round(p.get("enterpriseValueMultipleTTM", 0), 1) if p.get("enterpriseValueMultipleTTM") else None,
                "ps": round(p.get("priceToSalesRatioTTM", 0), 1) if p.get("priceToSalesRatioTTM") else None,
                "pb": round(p.get("priceToBookRatioTTM", 0), 1) if p.get("priceToBookRatioTTM") else None,
                "dcf_premium_pct": peer_dcf_premium,
            })

        # Calculate company DCF premium
        company_price = quote.get("price", 0)
        company_dcf_value = dcf_data.get("dcf", 0)
        company_dcf_premium = None
        if company_price and company_dcf_value:
            company_dcf_premium = round(((company_price - company_dcf_value) / company_dcf_value) * 100, 1)

        # Calculate average peer DCF premium for comparison
        peer_dcf_premiums = [p.get("dcf_premium_pct") for p in peer_comparison if p.get("dcf_premium_pct") is not None]
        avg_peer_dcf_premium = round(sum(peer_dcf_premiums) / len(peer_dcf_premiums), 1) if peer_dcf_premiums else None

        return {
            "ticker": ticker,
            "current_price": quote.get("price", 0),
            "signal": signal,
            "avg_premium_to_peers_pct": round(avg_premium, 1) if avg_premium else None,
            "company_multiples": {
                "pe": round(company_multiples["pe"], 1) if company_multiples["pe"] else None,
                "ev_ebitda": round(company_multiples["ev_ebitda"], 1) if company_multiples["ev_ebitda"] else None,
                "ps": round(company_multiples["ps"], 1) if company_multiples["ps"] else None,
                "pb": round(company_multiples["pb"], 1) if company_multiples["pb"] else None,
                "peg": round(company_multiples["peg"], 2) if company_multiples["peg"] else None,
                "pfcf": round(company_multiples["pfcf"], 1) if company_multiples["pfcf"] else None,
            },
            "peer_avg_multiples": {
                "pe": round(peer_multiples["pe"], 1) if peer_multiples["pe"] else None,
                "ev_ebitda": round(peer_multiples["ev_ebitda"], 1) if peer_multiples["ev_ebitda"] else None,
                "ps": round(peer_multiples["ps"], 1) if peer_multiples["ps"] else None,
                "pb": round(peer_multiples["pb"], 1) if peer_multiples["pb"] else None,
            },
            "vs_peers": {
                "pe_premium_pct": round(pe_vs_peers, 1) if pe_vs_peers else None,
                "ev_ebitda_premium_pct": round(ev_ebitda_vs_peers, 1) if ev_ebitda_vs_peers else None,
                "ps_premium_pct": round(ps_vs_peers, 1) if ps_vs_peers else None,
            },
            "vs_sector": {
                "sector": sector,
                "sector_pe": round(sector_pe, 1) if sector_pe else None,
                "pe_vs_sector_pct": round(pe_vs_sector, 1) if pe_vs_sector else None,
            },
            "vs_industry": {
                "industry": industry,
                "industry_pe": round(industry_pe, 1) if industry_pe else None,
            },
            "peer_comparison": peer_comparison,
            "peers_analyzed": len(peer_ratios),
            "dcf_analysis": {
                "company_dcf_value": round(company_dcf_value, 2) if company_dcf_value else None,
                "company_dcf_premium_pct": company_dcf_premium,
                "peer_avg_dcf_premium_pct": avg_peer_dcf_premium,
                "dcf_vs_peers": round(company_dcf_premium - avg_peer_dcf_premium, 1) if (company_dcf_premium is not None and avg_peer_dcf_premium is not None) else None,
                "note": "DCF premium = how much price exceeds DCF value. Compare to peers, not absolute.",
            },
        }

    # =========================================================================
    # SEC Filings
    # =========================================================================

    async def get_sec_filings(
        self,
        ticker: str,
        filing_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get SEC filings.

        Args:
            ticker: Stock ticker
            filing_type: Optional filter (e.g., "10-K", "10-Q", "8-K")
            limit: Number of filings

        Returns:
            List of SEC filings
        """
        params = {"limit": limit}
        if filing_type:
            params["type"] = filing_type

        return await self._request(f"/sec_filings/{ticker}", params=params)

    async def get_earnings_transcripts(
        self,
        ticker: str,
        year: Optional[int] = None,
        quarter: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get earnings call transcripts.

        Args:
            ticker: Stock ticker
            year: Optional year filter
            quarter: Optional quarter filter (1-4)

        Returns:
            List of transcripts
        """
        if year and quarter:
            endpoint = f"/earning_call_transcript/{ticker}"
            params = {"year": year, "quarter": quarter}
        else:
            endpoint = f"/earning_call_transcript/{ticker}"
            params = {}

        return await self._request(endpoint, params=params)

    # =========================================================================
    # Market Data
    # =========================================================================

    async def get_quote(self, ticker: str) -> Dict[str, Any]:
        """Get real-time quote."""
        data = await self._request(f"/quote/{ticker}", cache_hours=0)
        return data[0] if data else {}

    async def get_historical_prices(
        self,
        ticker: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get historical daily prices.

        Args:
            ticker: Stock ticker
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)

        Returns:
            Historical price data
        """
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        return await self._request(f"/historical-price-full/{ticker}", params=params)

    async def get_price_history(
        self,
        ticker: str,
        days: int = 365,
    ) -> Dict[str, Any]:
        """
        Get price history for the last N days.

        Args:
            ticker: Stock ticker
            days: Number of days of history

        Returns:
            Historical price data
        """
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        return await self.get_historical_prices(ticker, from_date, to_date)

    # =========================================================================
    # Analyst Data
    # =========================================================================

    async def get_analyst_estimates(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 4,
    ) -> List[Dict[str, Any]]:
        """Get analyst estimates."""
        return await self._request(
            f"/analyst-estimates/{ticker}",
            params={"period": period, "limit": limit},
        )

    async def get_analyst_recommendations(
        self,
        ticker: str,
    ) -> List[Dict[str, Any]]:
        """Get analyst recommendations."""
        return await self._request(f"/analyst-stock-recommendations/{ticker}")

    async def get_analyst_ratings(self, ticker: str) -> Dict[str, Any]:
        """
        Get analyst ratings summary.

        Returns:
            Dictionary with recommendations, estimates, and price targets
        """
        recommendations, estimates = await asyncio.gather(
            self.get_analyst_recommendations(ticker),
            self.get_analyst_estimates(ticker),
        )

        return {
            "recommendations": recommendations,
            "estimates": estimates,
        }

    async def get_price_target(self, ticker: str) -> List[Dict[str, Any]]:
        """Get analyst price targets."""
        return await self._request(f"/price-target/{ticker}")

    async def get_price_target_summary(self, ticker: str) -> Dict[str, Any]:
        """Get price target summary."""
        data = await self._request(f"/price-target-summary", params={"symbol": ticker}, use_v4=True)
        return data[0] if data else {}

    # =========================================================================
    # Earnings
    # =========================================================================

    async def get_earnings_surprises(self, ticker: str) -> List[Dict[str, Any]]:
        """Get earnings surprises history."""
        return await self._request(f"/earnings-surprises/{ticker}")

    async def get_earnings_calendar(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get earnings calendar."""
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        return await self._request("/earning_calendar", params=params)

    # =========================================================================
    # Insider and Institutional
    # =========================================================================

    async def get_insider_trading(self, ticker: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get insider trading data."""
        return await self._request(
            f"/insider-trading",
            params={"symbol": ticker, "limit": limit},
            use_v4=True,
        )

    async def get_institutional_holders(self, ticker: str) -> List[Dict[str, Any]]:
        """Get institutional holders."""
        return await self._request(f"/institutional-holder/{ticker}")

    async def get_institutional_ownership(self, ticker: str) -> List[Dict[str, Any]]:
        """
        Get institutional ownership with historical changes.
        Shows quarter-over-quarter changes in institutional holdings.
        """
        return await self._request(
            f"/institutional-ownership/symbol-ownership",
            params={"symbol": ticker, "includeCurrentQuarter": "true"},
            use_v4=True,
        )

    async def get_institutional_ownership_summary(self, ticker: str) -> Dict[str, Any]:
        """
        Get comprehensive institutional ownership data with changes.
        Aggregates current holders and calculates net changes.
        """
        ownership_history, current_holders = await asyncio.gather(
            self.get_institutional_ownership(ticker),
            self.get_institutional_holders(ticker),
            return_exceptions=True,
        )

        # Handle exceptions
        ownership_history = ownership_history if not isinstance(ownership_history, Exception) else []
        current_holders = current_holders if not isinstance(current_holders, Exception) else []

        # Calculate changes from ownership history
        changes_summary = {
            "increased_positions": 0,
            "decreased_positions": 0,
            "new_positions": 0,
            "sold_out_positions": 0,
            "total_institutions": len(current_holders),
        }

        # Get recent quarters for comparison
        recent_changes = []
        if ownership_history:
            # Group by investor and compare quarters
            for record in ownership_history[:100]:  # Limit for performance
                change = record.get("change", 0) or 0
                if change > 0:
                    changes_summary["increased_positions"] += 1
                elif change < 0:
                    changes_summary["decreased_positions"] += 1

                if record.get("isNew"):
                    changes_summary["new_positions"] += 1
                if record.get("soldOut"):
                    changes_summary["sold_out_positions"] += 1

                recent_changes.append({
                    "investor": record.get("investorName", ""),
                    "shares": record.get("shares", 0),
                    "change": change,
                    "change_pct": record.get("changePercentage", 0),
                    "date": record.get("dateReported", ""),
                })

        # Top holders
        top_holders = []
        for holder in current_holders[:15]:
            top_holders.append({
                "name": holder.get("holder", ""),
                "shares": holder.get("shares", 0),
                "value": holder.get("value", 0),
                "change": holder.get("change", 0),
                "date_reported": holder.get("dateReported", ""),
            })

        return {
            "summary": changes_summary,
            "top_holders": top_holders,
            "recent_changes": recent_changes[:20],
            "raw_history": ownership_history[:50] if ownership_history else [],
        }

    async def get_insider_trading_summary(self, ticker: str, limit: int = 100) -> Dict[str, Any]:
        """
        Get insider trading with focus on SIGNIFICANT BUYS.

        Key insight: Insider selling is noise (taxes, diversification, planned sales).
        Insider BUYING is the signal - they only buy when they believe stock is undervalued.

        Flags:
        - Large purchases (>$100K)
        - C-suite buying (CEO, CFO, COO)
        - Cluster buying (multiple insiders buying in same period)
        - Director purchases
        """
        trades = await self.get_insider_trading(ticker, limit)

        if not trades:
            return {
                "total_transactions": 0,
                "signal": "NO DATA",
                "significant_buys": [],
                "buy_signals": [],
                "summary": {},
            }

        buys = []
        sells = []
        significant_buys = []  # The important signal
        total_buy_value = 0
        total_sell_value = 0

        # Track buyers for cluster detection
        recent_buyers = set()

        for trade in trades:
            tx_type = trade.get("transactionType", "").upper()
            shares = abs(trade.get("securitiesTransacted", 0) or 0)
            price = trade.get("price", 0) or 0
            value = shares * price
            name = trade.get("reportingName", "")
            title = trade.get("typeOfOwner", "").upper()
            date = trade.get("transactionDate", "")

            entry = {
                "name": name,
                "title": title,
                "date": date,
                "type": tx_type,
                "shares": shares,
                "price": price,
                "value": value,
            }

            # Categorize as buy or sell
            is_buy = tx_type in ["P-PURCHASE", "PURCHASE", "P"]
            is_award = tx_type in ["A-AWARD", "M-EXEMPT"]  # Awards are not open market buys
            is_sell = tx_type in ["S-SALE", "SALE", "S", "F-TAX", "D-RETURN"]

            if is_buy:
                buys.append(entry)
                total_buy_value += value
                recent_buyers.add(name)

                # Flag significant buys (THE SIGNAL)
                is_significant = False
                signal_reasons = []

                # Large purchase (>$100K is notable, >$500K is very significant)
                if value >= 500000:
                    is_significant = True
                    signal_reasons.append(f"LARGE BUY (${value:,.0f})")
                elif value >= 100000:
                    is_significant = True
                    signal_reasons.append(f"Notable buy (${value:,.0f})")

                # C-suite buying is always significant
                if any(c in title for c in ["CEO", "CFO", "COO", "CHIEF"]):
                    is_significant = True
                    signal_reasons.append("C-SUITE PURCHASE")

                # Director buying is meaningful
                if "DIRECTOR" in title and value >= 50000:
                    is_significant = True
                    signal_reasons.append("Director purchase")

                if is_significant:
                    entry["signal_reasons"] = signal_reasons
                    significant_buys.append(entry)

            elif is_sell:
                sells.append(entry)
                total_sell_value += value
            # Note: Awards (is_award) are ignored - not open market transactions

        # Detect cluster buying (multiple insiders buying = stronger signal)
        cluster_buying = len(recent_buyers) >= 3

        # Determine signal strength
        if significant_buys:
            if any("C-SUITE" in str(b.get("signal_reasons", [])) for b in significant_buys):
                signal = "STRONG BUY SIGNAL - C-Suite Purchasing"
            elif cluster_buying:
                signal = "STRONG BUY SIGNAL - Cluster Buying"
            elif any("LARGE BUY" in str(b.get("signal_reasons", [])) for b in significant_buys):
                signal = "BUY SIGNAL - Large Insider Purchase"
            else:
                signal = "MODERATE BUY SIGNAL"
        else:
            signal = "NO SIGNIFICANT INSIDER BUYING"

        # Build buy signals summary
        buy_signals = []
        if significant_buys:
            buy_signals.append(f"{len(significant_buys)} significant purchase(s) detected")
        if cluster_buying:
            buy_signals.append(f"Cluster buying: {len(recent_buyers)} different insiders bought")
        c_suite_buys = [b for b in significant_buys if "C-SUITE" in str(b.get("signal_reasons", []))]
        if c_suite_buys:
            buy_signals.append(f"C-Suite buying: {', '.join(b['name'] for b in c_suite_buys)}")

        return {
            "total_transactions": len(trades),
            "signal": signal,
            "buy_signals": buy_signals,
            "significant_buys": significant_buys,  # THE KEY DATA
            "cluster_buying": cluster_buying,
            "unique_buyers": list(recent_buyers),
            "summary": {
                "total_buys": len(buys),
                "total_sells": len(sells),
                "buy_value": total_buy_value,
                "sell_value": total_sell_value,
                "significant_buy_count": len(significant_buys),
                "significant_buy_value": sum(b["value"] for b in significant_buys),
            },
            "recent_buys": buys[:10],
            "all_transactions": trades[:30],
        }

    async def get_etf_holders(self, ticker: str) -> List[Dict[str, Any]]:
        """
        Get ETFs that hold this stock.
        Returns list of ETFs with their holdings weight.
        """
        return await self._request(f"/etf-holder/{ticker}", use_v4=True)

    async def get_etf_stock_exposure(self, ticker: str) -> Dict[str, Any]:
        """
        Get comprehensive ETF exposure data for a stock.
        Includes which ETFs hold it and the weight.
        """
        etf_holders = await self.get_etf_holders(ticker)

        # Calculate summary stats
        total_etfs = len(etf_holders) if etf_holders else 0

        # Group by ETF type/category if available
        major_etfs = []
        if etf_holders:
            # Sort by weight (shares held as proxy)
            sorted_holders = sorted(
                etf_holders,
                key=lambda x: x.get("sharesNumber", 0) or 0,
                reverse=True
            )
            major_etfs = sorted_holders[:20]  # Top 20 ETF holders

        return {
            "total_etf_holders": total_etfs,
            "top_etf_holders": major_etfs,
            "raw_data": etf_holders[:50] if etf_holders else []  # Limit to 50 for context
        }

    # =========================================================================
    # News
    # =========================================================================

    async def get_news(
        self,
        ticker: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get stock news."""
        return await self._request(
            f"/stock_news",
            params={"tickers": ticker, "limit": limit},
        )

    async def get_press_releases(
        self,
        ticker: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get press releases."""
        return await self._request(
            f"/press-releases/{ticker}",
            params={"limit": limit},
        )

    # =========================================================================
    # Industry and Peers
    # =========================================================================

    async def get_stock_peers(self, ticker: str) -> List[str]:
        """Get stock peers."""
        data = await self._request(f"/stock_peers", params={"symbol": ticker}, use_v4=True)
        if data and len(data) > 0 and "peersList" in data[0]:
            return data[0]["peersList"]
        return []

    async def get_sector_performance(self) -> List[Dict[str, Any]]:
        """Get sector performance."""
        return await self._request("/sector-performance")

    async def get_industry_data(self, ticker: str) -> Dict[str, Any]:
        """
        Get industry and peer data for a ticker.

        Returns:
            Dictionary with peers, sector performance
        """
        peers, sector_perf = await asyncio.gather(
            self.get_stock_peers(ticker),
            self.get_sector_performance(),
        )

        return {
            "peers": peers,
            "sector_performance": sector_perf,
        }

    async def get_peer_data(self, ticker: str) -> List[Dict[str, Any]]:
        """
        Get detailed data for peer companies.

        Returns:
            List of peer company profiles
        """
        peers = await self.get_stock_peers(ticker)

        if not peers:
            return []

        # Fetch profiles for up to 5 peers
        peer_profiles = await asyncio.gather(
            *[self.get_company_profile(peer) for peer in peers[:5]]
        )

        return [p for p in peer_profiles if p]

    # =========================================================================
    # S&P 500 Constituents
    # =========================================================================

    async def get_sp500_constituents(self) -> List[Dict[str, Any]]:
        """Get current S&P 500 constituents."""
        return await self._request("/sp500_constituent")

    async def get_historical_sp500_constituents(self) -> List[Dict[str, Any]]:
        """Get historical S&P 500 constituent changes."""
        return await self._request("/historical/sp500_constituent")

    # =========================================================================
    # NEW: Financial Scores & Advanced Metrics (saves LLM tokens)
    # =========================================================================

    async def get_financial_scores(self, ticker: str) -> Dict[str, Any]:
        """
        Get financial health scores including Altman Z-Score and Piotroski F-Score.

        These are pre-calculated by FMP - no need to use LLM for this.
        """
        data = await self._request(f"/score", params={"symbol": ticker}, use_v4=True)
        return data[0] if data else {}

    async def get_owner_earnings(self, ticker: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get Buffett-style owner earnings."""
        return await self._request(f"/owner_earnings", params={"symbol": ticker, "limit": limit}, use_v4=True)

    async def get_enterprise_values(self, ticker: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get historical enterprise values."""
        return await self._request(
            f"/enterprise-values/{ticker}",
            params={"limit": limit},
        )

    # =========================================================================
    # NEW: Revenue Segmentation
    # =========================================================================

    async def get_revenue_by_product(self, ticker: str) -> List[Dict[str, Any]]:
        """Get revenue breakdown by product line."""
        return await self._request(
            f"/revenue-product-segmentation",
            params={"symbol": ticker, "structure": "flat"},
            use_v4=True,
        )

    async def get_revenue_by_geography(self, ticker: str) -> List[Dict[str, Any]]:
        """Get revenue breakdown by geographic region."""
        return await self._request(
            f"/revenue-geographic-segmentation",
            params={"symbol": ticker, "structure": "flat"},
            use_v4=True,
        )

    async def get_revenue_segmentation(self, ticker: str) -> Dict[str, Any]:
        """Get both product and geographic revenue segmentation."""
        product, geography = await asyncio.gather(
            self.get_revenue_by_product(ticker),
            self.get_revenue_by_geography(ticker),
        )
        return {
            "by_product": product,
            "by_geography": geography,
        }

    # =========================================================================
    # NEW: Technical Indicators (from FMP, not calculated by LLM)
    # =========================================================================

    async def get_technical_indicator(
        self,
        ticker: str,
        indicator: str,
        period: int = 14,
        timeframe: str = "1day",
    ) -> List[Dict[str, Any]]:
        """
        Get technical indicator data.

        Args:
            ticker: Stock symbol
            indicator: One of: sma, ema, wma, dema, tema, rsi, williams, adx, standarddeviation
            period: Indicator period
            timeframe: 1min, 5min, 15min, 30min, 1hour, 4hour, 1day
        """
        return await self._request(
            f"/technical_indicator/{timeframe}/{ticker}",
            params={"period": period, "type": indicator},
            use_v4=True,
        )

    async def get_technical_indicators_bundle(self, ticker: str) -> Dict[str, Any]:
        """
        Get common technical indicators in one call.

        Returns RSI, SMA(20,50,200), and EMA(20,50) - pre-calculated by FMP.
        """
        rsi, sma_20, sma_50, sma_200, ema_20 = await asyncio.gather(
            self.get_technical_indicator(ticker, "rsi", period=14),
            self.get_technical_indicator(ticker, "sma", period=20),
            self.get_technical_indicator(ticker, "sma", period=50),
            self.get_technical_indicator(ticker, "sma", period=200),
            self.get_technical_indicator(ticker, "ema", period=20),
        )

        return {
            "rsi_14": rsi[0] if rsi else {},
            "sma_20": sma_20[0] if sma_20 else {},
            "sma_50": sma_50[0] if sma_50 else {},
            "sma_200": sma_200[0] if sma_200 else {},
            "ema_20": ema_20[0] if ema_20 else {},
        }

    # =========================================================================
    # NEW: Sector/Industry Context
    # =========================================================================

    async def get_sector_pe(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get P/E ratios by sector."""
        params = {}
        if date:
            params["date"] = date
        return await self._request("/sector_price_earning_ratio", params=params, use_v4=True)

    async def get_industry_pe(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get P/E ratios by industry."""
        params = {}
        if date:
            params["date"] = date
        return await self._request("/industry_price_earning_ratio", params=params, use_v4=True)

    # =========================================================================
    # NEW: Economic Data (for DCF and macro context)
    # =========================================================================

    async def get_treasury_rates(self) -> List[Dict[str, Any]]:
        """Get current Treasury rates (useful for DCF risk-free rate)."""
        return await self._request("/treasury", use_v4=True)

    async def get_economic_indicator(self, indicator: str) -> List[Dict[str, Any]]:
        """
        Get economic indicator data.

        Args:
            indicator: One of: GDP, realGDP, nominalPotentialGDP, realGDPPerCapita,
                      federalFunds, CPI, inflationRate, inflation, retailSales,
                      consumerSentiment, durableGoods, unemploymentRate, etc.
        """
        return await self._request(f"/economic", params={"name": indicator}, use_v4=True)

    # =========================================================================
    # NEW: Additional Company Data
    # =========================================================================

    async def get_employee_count(self, ticker: str) -> List[Dict[str, Any]]:
        """Get historical employee count."""
        return await self._request(f"/historical/employee_count", params={"symbol": ticker}, use_v4=True)

    async def get_shares_float(self, ticker: str) -> Dict[str, Any]:
        """Get share float data."""
        data = await self._request(f"/shares_float", params={"symbol": ticker}, use_v4=True)
        return data[0] if data else {}

    async def get_stock_grade(self, ticker: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get analyst grades (buy/sell/hold ratings)."""
        return await self._request(f"/grade/{ticker}", params={"limit": limit})

    async def get_price_target_consensus(self, ticker: str) -> Dict[str, Any]:
        """Get price target consensus (high, low, median, average)."""
        data = await self._request(f"/price-target-consensus", params={"symbol": ticker}, use_v4=True)
        return data[0] if data else {}

    async def get_analyst_grades_summary(self, ticker: str) -> Dict[str, Any]:
        """Get summary of analyst ratings."""
        data = await self._request(f"/grade-summary", params={"symbol": ticker}, use_v4=True)
        return data[0] if data else {}

    async def get_dividends(self, ticker: str) -> List[Dict[str, Any]]:
        """Get dividend history."""
        return await self._request(f"/historical-price-full/stock_dividend/{ticker}")

    async def get_stock_splits(self, ticker: str) -> List[Dict[str, Any]]:
        """Get stock split history."""
        return await self._request(f"/historical-price-full/stock_split/{ticker}")

    # =========================================================================
    # NEW: Validation
    # =========================================================================

    async def is_valid_ticker(self, ticker: str) -> bool:
        """Check if ticker is valid and actively trading."""
        profile = await self.get_company_profile(ticker)
        if not profile:
            return False
        return profile.get("isActivelyTrading", False)

    # =========================================================================
    # SCANNER: Market Movers & Signals
    # =========================================================================

    async def get_biggest_gainers(self) -> List[Dict[str, Any]]:
        """
        Get today's biggest gaining stocks.

        Returns stocks with largest price increases for signal detection.
        """
        return await self._request("/biggest-gainers", use_stable=True, cache_hours=1)

    async def get_biggest_losers(self) -> List[Dict[str, Any]]:
        """Get today's biggest losing stocks."""
        return await self._request("/biggest-losers", use_stable=True, cache_hours=1)

    async def get_most_active(self) -> List[Dict[str, Any]]:
        """
        Get most actively traded stocks by volume.

        High volume often indicates institutional activity.
        """
        return await self._request("/most-actives", use_stable=True, cache_hours=1)

    async def get_batch_quotes(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """
        Get quotes for multiple tickers in one call.

        More efficient than calling get_quote() for each ticker.
        """
        if not tickers:
            return []
        symbols = ",".join(tickers[:50])  # Limit to 50 per batch
        return await self._request(f"/quote/{symbols}", cache_hours=0)

    async def get_stock_screener(
        self,
        market_cap_min: Optional[int] = None,
        market_cap_max: Optional[int] = None,
        volume_min: Optional[int] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        sector: Optional[str] = None,
        exchange: Optional[str] = None,
        is_etf: bool = False,
        is_actively_trading: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Screen stocks based on various criteria.

        Useful for filtering universe before signal detection.
        """
        params = {"limit": limit, "isEtf": str(is_etf).lower(), "isActivelyTrading": str(is_actively_trading).lower()}

        if market_cap_min:
            params["marketCapMoreThan"] = market_cap_min
        if market_cap_max:
            params["marketCapLowerThan"] = market_cap_max
        if volume_min:
            params["volumeMoreThan"] = volume_min
        if price_min:
            params["priceMoreThan"] = price_min
        if price_max:
            params["priceLowerThan"] = price_max
        if sector:
            params["sector"] = sector
        if exchange:
            params["exchange"] = exchange

        return await self._request("/company-screener", params=params, use_stable=True)

    # =========================================================================
    # SCANNER: Technical Indicators (Stable API)
    # =========================================================================

    async def get_sma(
        self,
        ticker: str,
        period: int = 50,
        timeframe: str = "1day",
    ) -> List[Dict[str, Any]]:
        """
        Get Simple Moving Average from stable API.

        Args:
            ticker: Stock symbol
            period: SMA period (e.g., 20, 50, 200)
            timeframe: 1min, 5min, 15min, 30min, 1hour, 4hour, 1day
        """
        return await self._request(
            "/technical-indicators/sma",
            params={"symbol": ticker, "periodLength": period, "timeframe": timeframe},
            use_stable=True,
            cache_hours=1,
        )

    async def get_rsi(
        self,
        ticker: str,
        period: int = 14,
        timeframe: str = "1day",
    ) -> List[Dict[str, Any]]:
        """Get Relative Strength Index."""
        return await self._request(
            "/technical-indicators/rsi",
            params={"symbol": ticker, "periodLength": period, "timeframe": timeframe},
            use_stable=True,
            cache_hours=1,
        )

    async def get_ema(
        self,
        ticker: str,
        period: int = 20,
        timeframe: str = "1day",
    ) -> List[Dict[str, Any]]:
        """Get Exponential Moving Average."""
        return await self._request(
            "/technical-indicators/ema",
            params={"symbol": ticker, "periodLength": period, "timeframe": timeframe},
            use_stable=True,
            cache_hours=1,
        )

    # =========================================================================
    # SCANNER: News (Stable API)
    # =========================================================================

    async def get_stock_news_stable(
        self,
        tickers: List[str],
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get news for multiple stocks using stable API.

        Better for scanner - can fetch news for multiple tickers at once.
        """
        if not tickers:
            return []
        symbols = ",".join(tickers[:10])  # Limit to 10 tickers
        return await self._request(
            "/news/stock",
            params={"symbols": symbols, "limit": limit},
            use_stable=True,
            cache_hours=1,
        )

    async def get_general_news(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get general market news."""
        return await self._request(
            "/news/general",
            params={"limit": limit},
            use_stable=True,
            cache_hours=1,
        )

    # =========================================================================
    # SCANNER: Helper Methods
    # =========================================================================

    async def get_scanner_data(self, ticker: str) -> Dict[str, Any]:
        """
        Get all data needed for signal detection on a single stock.

        Fetches quote, SMAs, and RSI in parallel.
        """
        quote, sma_20, sma_50, sma_200, rsi = await asyncio.gather(
            self.get_quote(ticker),
            self.get_sma(ticker, period=20),
            self.get_sma(ticker, period=50),
            self.get_sma(ticker, period=200),
            self.get_rsi(ticker, period=14),
            return_exceptions=True,
        )

        # Extract latest values
        def safe_get(data, key="sma"):
            if isinstance(data, Exception) or not data:
                return None
            return data[0].get(key) if data else None

        return {
            "ticker": ticker,
            "quote": quote if not isinstance(quote, Exception) else {},
            "sma_20": safe_get(sma_20, "sma"),
            "sma_50": safe_get(sma_50, "sma"),
            "sma_200": safe_get(sma_200, "sma"),
            "rsi_14": safe_get(rsi, "rsi"),
        }
