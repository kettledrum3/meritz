import os
import sys
import pandas as pd
import math
from typing import Tuple, List, Literal, Union, Optional

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.cavr import Broker, ValueRebalancingEngine, VRConfig, CostAveragingEngine, CAConfig

def format_currency(val, m_code):
    """시장별 통화 포맷팅 (KR은 소수점 제거, US는 소수점 2자리, 공통 천단위 콤마)"""
    try:
        num_val = float(val)
        if m_code == "KR":
            return f"{int(num_val):,}"
        return f"{num_val:,.2f}"
    except (ValueError, TypeError):
        return str(val)

class BacktestBroker(Broker):
    """CSV 데이터를 기반으로 주식 시장과 계좌를 시뮬레이션하는 브로커"""
    
    def __init__(self, df: pd.DataFrame, initial_cash: float = 10000.0, initial_shares: float = 0.0, fee_rate: float = 0.0, market: str = "US", tax_rate: float = 0.0, etf_tickers: List[str] = None):
        self.df = df
        self.current_idx = 0
        self.cash = initial_cash
        self.shares = initial_shares
        self.fee_rate = fee_rate
        self.market = market
        self.tax_rate = tax_rate
        self.etf_tickers = etf_tickers or []
        self.trade_history = []
        
        # 누적 매수 원금 명시적 관리
        self.cumulative_buy_amount = 0.0
        self.avg_price = 0.0
        
        # 총 투입 원금 (초기자본 + 적립/인출 누적)
        self.net_principal = initial_cash
        
        # POOL 사용 한도 관리 (VR 전략용)
        self.cycle_buy_limit = float('inf')
        self.cycle_buy_usage = 0.0

        if initial_shares > 0:
            initial_price = self._get_current_close()
            self.avg_price = initial_price
            self.cumulative_buy_amount = initial_price * initial_shares

    def add_cash(self, amount: float):
        """주기적 입출금을 위해 계좌에 현금을 추가/차감합니다."""
        if amount != 0:
            self.cash += amount
            self.net_principal += amount

    def _get_current_close(self) -> float:
        return float(self.df.iloc[self.current_idx]['Close'])

    def _get_current_date(self):
        return self.df.iloc[self.current_idx]['Date']

    def next(self) -> bool:
        if self.current_idx < len(self.df) - 1:
            self.current_idx += 1
            return True
        return False

    def get_price(self, symbol: str) -> float:
        return self._get_current_close()
    
    def get_previous_close(self, symbol: str) -> float:
        """직전 거래일 종가 반환 (백테스트 시뮬레이션용)"""
        if self.current_idx > 0:
            return float(self.df.iloc[self.current_idx - 1]['Close'])
        else:
            row = self.df.iloc[self.current_idx]
            if 'Open' in row:
                return float(row['Open'])
            return float(row['Close'])
    
    def get_current_high(self, symbol: str = None) -> float:
        """현재 캔들의 고가 반환 (VR 매도 조건 체크용)"""
        return float(self.df.iloc[self.current_idx]['High'])

    def get_current_low(self, symbol: str = None) -> float:
        """현재 캔들의 저가 반환 (VR 매수 조건 체크용)"""
        return float(self.df.iloc[self.current_idx]['Low'])

    def get_account_equity(self, symbol: str) -> Tuple[float, float, float]:
        current_price = self._get_current_close()
        eval_amt = self.shares * current_price
        return self.shares, self.avg_price, eval_amt

    def get_cumulative_buy_amount(self, symbol: str) -> float:
        return self.cumulative_buy_amount

    def get_cash_pool(self) -> float:
        return self.cash

    def set_cycle_limit(self, limit: float):
        """새로운 사이클의 매수 한도를 설정합니다."""
        self.cycle_buy_limit = limit
        self.cycle_buy_usage = 0.0

    def fetch_open_orders(self, symbol: str) -> List[dict]:
        return []

    def adjust_price_by_tick(self, symbol: str, price: float, order_type: Literal["BUY", "SELL"]) -> float:
        """호가 단위에 맞게 가격 보정 (KR 시장 특화 로직 포함)"""
        if self.market != "KR":
            return round(price, 2)
        
        p = abs(price)
        is_etf = symbol.upper() in [t.upper() for t in self.etf_tickers]
        
        tick = 1
        if is_etf:
            tick = 1 if p < 2000 else 5
        else:
            if p < 2000: tick = 1
            elif p < 5000: tick = 5
            elif p < 20000: tick = 10
            elif p < 50000: tick = 50
            elif p < 200000: tick = 100
            elif p < 500000: tick = 500
            else: tick = 1000
            
        if order_type == "BUY":
            return float(math.ceil(price / tick) * tick)
        else:
            return float(math.floor(price / tick) * tick)

    def place_order(self, symbol: str, price: float, qty: float, order_type: Literal["BUY", "SELL"], price_type: str = "00", strategy: str = "MANUAL", strategy_name: str = "", stop_price: Optional[float] = None) -> bool:
        if qty <= 0: return False
        qty = int(qty)
        if qty <= 0: return False

        price = self.adjust_price_by_tick(symbol, price, order_type)

        row = self.df.iloc[self.current_idx]
        curr_close = float(row['Close'])
        curr_high = float(row['High'])
        curr_low = float(row['Low'])

        can_execute = False
        if price_type in ["00", "0", "LIMIT"]:
            if order_type == "BUY":
                if curr_low <= price: can_execute = True
            else:
                if curr_high >= price: can_execute = True
        elif price_type in ["30", "34", "33", "LOC", "MOC"]:
            if order_type == "BUY":
                if curr_close <= price or price_type in ["33", "MOC"]: can_execute = True
            else:
                if curr_close >= price or price_type in ["33", "MOC"]: can_execute = True
            price = curr_close
        else:
            can_execute = True

        success = False
        if order_type == "BUY" and can_execute:
            cost = price * qty
            if self.cycle_buy_usage + cost > self.cycle_buy_limit:
                return False
            
            fee = cost * self.fee_rate
            total_deduction = cost + fee
            
            if self.cash >= total_deduction:
                self.cumulative_buy_amount += cost
                self.cycle_buy_usage += cost
                self.shares += qty
                self.cash -= total_deduction
                if self.shares > 0:
                    self.avg_price = self.cumulative_buy_amount / self.shares
                success = True
            else:
                success = False

        elif order_type == "SELL" and can_execute:
            if self.shares >= qty:
                proceeds = price * qty
                fee = proceeds * self.fee_rate
                tax = proceeds * self.tax_rate if self.market == "KR" else 0.0
                total_addition = proceeds - fee - tax
                
                cost_of_sold_shares = self.avg_price * qty
                self.cumulative_buy_amount -= cost_of_sold_shares
                
                self.shares -= qty
                self.cash += total_addition
                if self.shares <= 0.0001:
                    self.shares = 0.0
                    self.avg_price = 0.0
                    self.cumulative_buy_amount = 0.0
                success = True
            else:
                success = False

        if success:
            self.trade_history.append({
                "Date": self._get_current_date(),
                "type": order_type,
                "price": price,
                "qty": qty
            })
            
        return success

def run_backtest(
    strategy_type: str, 
    symbol: str, 
    file_path: str, 
    initial_cash: float = 10000.0,
    **kwargs
) -> Tuple[str, pd.DataFrame, pd.DataFrame]:
    """백테스트 실행 및 결과 리포트(str), 결과 데이터(DataFrame) 반환"""
    
    if not os.path.exists(file_path):
        return f"Error: 데이터 파일을 찾을 수 없습니다: {file_path}", pd.DataFrame(), pd.DataFrame()

    try:
        if file_path.lower().endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path)
        else:
            return f"Error: 지원하지 않는 파일 형식입니다. (.csv, .xlsx, .xls): {file_path}", pd.DataFrame(), pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]

        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date').reset_index(drop=True)
        else:
            return "Error: 데이터 파일에 'Date' 컬럼이 필요합니다.", pd.DataFrame(), pd.DataFrame()
        
        for col in ['Open', 'High', 'Low', 'Close', 'Volume', '% Change']:
            if col in df.columns and df[col].dtype == object:
                df[col] = df[col].astype(str).str.replace(',', '').str.replace('%', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
    except Exception as e:
        return f"Error loading data file: {str(e)}", pd.DataFrame(), pd.DataFrame()

    market = kwargs.get("market", "US")
    default_fee = 0.000038 if market == "KR" else 0.0009
    default_tax = 0.0020 if market == "KR" else 0.0000206
    fee_rate = kwargs.get("fee_rate", default_fee)
    tax_rate = kwargs.get("tax_rate", default_tax)
    
    from core.cavr import load_etf_list
    env_suffix = "kr" if market == "KR" else "us"
    etf_list_path = os.path.join(os.path.dirname(__file__), '..', 'env', f'ETF_list_{env_suffix}.txt')
    etf_tickers = load_etf_list(etf_list_path)

    broker = BacktestBroker(df, initial_cash=initial_cash, fee_rate=fee_rate, market=market, tax_rate=tax_rate, etf_tickers=etf_tickers)
    
    temp_state_path = f"temp_backtest_{symbol}_{strategy_type}.json"
    if os.path.exists(temp_state_path):
        os.remove(temp_state_path)

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)

    engine = None
    if strategy_type == "VR":
        p_acc = kwargs.get("periodic_accumulation", 0.0)
        invest_type = kwargs.get("invest_type", "")
        
        def_limit_pct = 50.0
        if str(invest_type) == "적립식" or str(invest_type) == "accumulation" or p_acc > 0:
            def_limit_pct = 75.0
        elif str(invest_type) == "인출식" or str(invest_type) == "withdrawal" or p_acc < 0:
            def_limit_pct = 25.0
            
        pool_limit_pct = kwargs.get("pool_limit_pct", def_limit_pct)

        config = VRConfig(
            symbol=symbol,
            strategy_type="VR",
            save_path=temp_state_path,
            initial_budget=initial_cash,
            G=kwargs.get("G", 10.0),
            band_low_pct=kwargs.get("band_low_pct", 85.0),
            band_high_pct=kwargs.get("band_high_pct", 115.0),
            periodic_accumulation=p_acc,
            investment_type="accumulation" if p_acc > 0 or invest_type == "적립식" else "deferment",
            pool_limit_pct=pool_limit_pct
        )
        engine = ValueRebalancingEngine(config, broker)
        
    elif strategy_type == "CA":
        a_default = int(kwargs.get("a_default", 40))
        unit_buy = kwargs.get("unit_buy_amount", 0.0)
        
        trade_history_path = os.path.join(data_dir, f'backtest_trade_history_{symbol}.csv')
        if os.path.exists(trade_history_path):
            os.remove(trade_history_path)

        config = CAConfig(
            symbol=symbol,
            strategy_type="CA",
            save_path=temp_state_path,
            initial_budget=initial_cash,
            unit_buy_amount=unit_buy,
            a_default=a_default,
            T_default=int(kwargs.get("T_default", 40)),
            target_profit_pct=kwargs.get("target_profit_pct", 0.1),
            use_quarter_stop=kwargs.get("use_quarter_stop", True),
            fee_rate=fee_rate,
            trade_history_path=trade_history_path
        )
        engine = CostAveragingEngine(config, broker)
    
    print(f"--- Backtest Start: {symbol} ({strategy_type}) ---")
    
    daily_logs = []

    actual_contribution_dates = set()
    accumulation_amount = 0.0
    if strategy_type == "VR":
        contribution_frequency_str = kwargs.get("contribution_frequency", "없음")
        accumulation_amount = kwargs.get("periodic_accumulation", 0.0)
        
        freq_map = {
            "매주 금요일": 1,
            "격주 금요일 (2주)": 2,
            "3주마다 금요일": 3,
            "4주마다 금요일": 4,
        }
        contribution_week_period = freq_map.get(contribution_frequency_str, 0)

        if contribution_week_period > 0:
            start_date = df['Date'].iloc[0]
            end_date = df['Date'].iloc[-1]
            all_fridays = pd.to_datetime(pd.date_range(start=start_date, end=end_date, freq='W-FRI'))
            scheduled_fridays = all_fridays[::contribution_week_period]
            all_trading_days = pd.to_datetime(df['Date'])
            for s_friday in scheduled_fridays:
                next_trading_day = all_trading_days[all_trading_days >= s_friday].min()
                if pd.notna(next_trading_day):
                    actual_contribution_dates.add(next_trading_day)
        else:
            all_dates = df['Date'].tolist()
            for i in range(0, len(all_dates), 10):
                actual_contribution_dates.add(all_dates[i])
    
    vr_limit_ratio = 1.0
    if strategy_type == "VR" and engine is not None:
        vr_limit_ratio = engine.config.pool_limit_pct / 100.0

    while True:
        current_date = broker._get_current_date()
        daily_accumulation = 0.0
        is_cycle_start_day = False

        if strategy_type == "VR":
            if current_date in actual_contribution_dates:
                if contribution_week_period > 0:
                    daily_accumulation = accumulation_amount
                    broker.add_cash(daily_accumulation)
                is_cycle_start_day = True

        if isinstance(engine, ValueRebalancingEngine):
            if broker.current_idx == 0: is_cycle_start_day = True
            engine.run_cycle(date=current_date, contribution=daily_accumulation, is_cycle_start_day=is_cycle_start_day)
            
            if is_cycle_start_day:
                current_pool = broker.get_cash_pool()
                broker.set_cycle_limit(current_pool * vr_limit_ratio)
        else:
            engine.run_cycle(date=current_date)
        
        price = broker.get_price(symbol)
        total_equity = broker.cash + (broker.shares * price)
        
        log_entry = {
            "Date": current_date,
            "Close": price,
            "TotalEquity": total_equity,
            "Cash": broker.cash,
            "Shares": broker.shares,
            "AvgPrice": broker.avg_price,
            "CumulativeBuyAmount": broker.get_cumulative_buy_amount(symbol),
            "NetPrincipal": broker.net_principal
        }
        
        if strategy_type == "CA":
            log_entry["Turn"] = engine.state.current_turn
            log_entry["Mode"] = engine.state.mode
        elif strategy_type == "VR":
            log_entry["Target_V"] = engine.state.V
            log_entry["Pool"] = engine.state.pool
            log_entry["Accumulation"] = daily_accumulation

        daily_logs.append(log_entry)
        
        if not broker.next():
            break

    if os.path.exists(temp_state_path):
        os.remove(temp_state_path)

    result_df = pd.DataFrame(daily_logs)
    trade_history_df = pd.DataFrame(broker.trade_history)
    
    save_filename = f'backtest_result_{symbol}_{strategy_type}.csv'
    save_path = os.path.join(data_dir, save_filename)
    
    try:
        result_df.to_csv(save_path, index=False)
        save_message = f"Result File:    {save_path}"
    except PermissionError:
        error_msg = f"Permission denied for '{save_path}'."
        save_message = f"SAVE FAILED: {error_msg}"

    # MDD 계산
    result_df['Peak'] = result_df['TotalEquity'].cummax()
    result_df['Drawdown'] = (result_df['TotalEquity'] - result_df['Peak']) / result_df['Peak']
    mdd = result_df['Drawdown'].min() * 100

    win_rate_str = "N/A"
    total_cycles = 0
    win_cycles = 0

    if strategy_type == "CA":
        trade_history_path = os.path.join(data_dir, f'backtest_trade_history_{symbol}.csv')
        if os.path.exists(trade_history_path):
            try:
                th_df = pd.read_csv(trade_history_path)
                if not th_df.empty:
                    total_cycles = len(th_df)
                    win_cycles = len(th_df[th_df['profit'] > 0])
                    if total_cycles > 0:
                        win_rate = (win_cycles / total_cycles) * 100
                        win_rate_str = f"{win_rate:.2f}% ({win_cycles}/{total_cycles})"
                    else:
                        win_rate_str = "0.00% (0/0)"
            except Exception as e:
                print(f"[Warning] 승률 계산 중 오류: {e}")

    currency_symbol = "₩" if market == "KR" else "$"
    start_equity = initial_cash
    final_equity = result_df.iloc[-1]['TotalEquity']
    final_net_principal = result_df.iloc[-1]['NetPrincipal']
    net_profit = final_equity - final_net_principal

    return_pct = 0.0
    if final_net_principal > 0:
        return_pct = (net_profit / final_net_principal) * 100
        
    start_date = result_df.iloc[0]['Date']
    end_date = result_df.iloc[-1]['Date']
    days = (end_date - start_date).days
    years = days / 365.25
    
    cagr_str = "N/A"
    if years > 0 and final_net_principal > 0 and final_equity > 0:
        cagr = (final_equity / final_net_principal) ** (1 / years) - 1
        cagr_str = f"{cagr * 100:.2f}%"
    
    summary_lines = [
        f"=== Backtest Result ({symbol}) ===",
        f"Strategy:       {strategy_type}",
        f"Ticker:         {symbol}",
        f"Period:         {len(df)} days",
        f"Fee Rate:       {fee_rate*100:.4f}%",
    ]

    if strategy_type == "CA":
        u_buy = kwargs.get("unit_buy_amount", 0.0)
        a_def = int(kwargs.get("a_default", 40))
        if u_buy <= 0 and a_def > 0:
            u_buy = initial_cash / a_def
        summary_lines.append(f"Buy Amount:     {currency_symbol}{format_currency(u_buy, market)}")
        summary_lines.append(f"Target Profit:  {kwargs.get('target_profit_pct', 0.1)*100:.1f}%")
        summary_lines.append(f"Split (a):      {a_def}")

    summary_lines.extend([
        f"Initial Equity: {currency_symbol}{format_currency(start_equity, market)}",
        f"Net Principal:  {currency_symbol}{format_currency(final_net_principal, market)}",
        f"Final Equity:   {currency_symbol}{format_currency(final_equity, market)}",
        f"Net Profit:     {currency_symbol}{format_currency(net_profit, market)}",
        f"Return:         {return_pct:.2f}%",
        f"CAGR:           {cagr_str}",
        f"MDD:            {mdd:.2f}%",
        f"Win Rate:       {win_rate_str}",
        save_message
    ])
    
    return "\n".join(summary_lines), result_df, trade_history_df
