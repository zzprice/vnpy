from datetime import datetime
from typing import Dict, List, Callable
from types import ModuleType

from vnpy.trader.object import ContractData, TickData, TradeData
from vnpy.trader.constant import Exchange, OptionType, Direction, Offset
from vnpy.trader.converter import PositionHolding

from .time import calculate_days_to_expiry, ANNUAL_DAYS


APP_NAME = "OptionMaster"

EVENT_OPTION_LOG = "eOptionLog"
EVENT_OPTION_NEW_PORTFOLIO = "eOptionNewPortfolio"


CHAIN_UNDERLYING_MAP = {
    "510050_O.SSE": "510050",
    "IO.CFFEX": "IF",
    "HO.CFFEX": "IH"
}


class InstrumentData:
    """"""

    def __init__(self, contract: ContractData):
        """"""
        self.symbol: str = contract.symbol
        self.exchange: Exchange = contract.exchange
        self.vt_symbol: str = contract.vt_symbol

        self.pricetick: float = contract.pricetick
        self.min_volume: float = contract.min_volume
        self.size: int = contract.size

        self.long_pos: int = 0
        self.short_pos: int = 0
        self.net_pos: int = 0
        self.mid_price: float = 0

        self.tick: TickData = None
        self.portfolio: PortfolioData = None

    def calculate_net_pos(self):
        """"""
        self.net_pos = self.long_pos - self.short_pos

    def update_tick(self, tick: TickData):
        """"""
        self.tick = tick
        self.mid_price = (tick.bid_price_1 + tick.ask_price_1) / 2

    def update_trade(self, trade: TradeData):
        """"""
        if trade.direction == Direction.LONG:
            if trade.offset == Offset.OPEN:
                self.long_pos += trade.volume
            else:
                self.short_pos -= trade.volume
        else:
            if trade.offset == Offset.OPEN:
                self.short_pos += trade.volume
            else:
                self.long_pos -= trade.volume
        self.calculate_net_pos()

    def update_holding(self, holding: PositionHolding):
        """"""
        self.long_pos = holding.long_pos
        self.short_pos = holding.short_pos
        self.calculate_net_pos()

    def set_portfolio(self, portfolio: "PortfolioData"):
        """"""
        self.portfolio = portfolio


class OptionData(InstrumentData):
    """"""

    def __init__(self, contract: ContractData):
        """"""
        super().__init__(contract)

        # Option contract features
        self.strike_price: float = contract.option_strike
        self.chain_index: str = contract.option_index

        self.option_type: int = 0
        if contract.option_type == OptionType.CALL:
            self.option_type = 1
        else:
            self.option_type = -1

        self.option_expiry: datetime = contract.option_expiry
        self.days_to_expiry: int = calculate_days_to_expiry(
            contract.option_expiry
        )
        self.time_to_expiry: float = self.days_to_expiry / ANNUAL_DAYS

        self.interest_rate: float = 0

        # Option portfolio related
        self.underlying: UnderlyingData = None
        self.chain: ChainData = None
        self.underlying_adjustment: float = 0

        # Pricing model
        self.calculate_price: Callable = None
        self.calculate_greeks: Callable = None
        self.calculate_impv: Callable = None

        # Implied volatility
        self.bid_impv: float = 0
        self.ask_impv: float = 0
        self.mid_impv: float = 0

        # Greeks related
        self.pricing_impv: float = 0

        self.theo_price: float = 0
        self.theo_delta: float = 0
        self.theo_gamma: float = 0
        self.theo_theta: float = 0
        self.theo_vega: float = 0

        self.pos_value: float = 0
        self.pos_delta: float = 0
        self.pos_gamma: float = 0
        self.pos_theta: float = 0
        self.pos_vega: float = 0

    def calculate_option_impv(self):
        """"""
        if not self.tick:
            return

        underlying_price = self.underlying.mid_price
        if not underlying_price:
            return
        underlying_price += self.underlying_adjustment

        self.ask_impv = self.calculate_impv(
            self.tick.ask_price_1,
            underlying_price,
            self.strike_price,
            self.interest_rate,
            self.time_to_expiry,
            self.option_type
        )

        self.bid_impv = self.calculate_impv(
            self.tick.bid_price_1,
            underlying_price,
            self.strike_price,
            self.interest_rate,
            self.time_to_expiry,
            self.option_type
        )

        self.mid_impv = (self.ask_impv + self.bid_impv) / 2
        self.pricing_impv = self.mid_impv

    def calculate_theo_greeks(self):
        """"""
        underlying_price = self.underlying.mid_price
        if not underlying_price or not self.pricing_impv:
            return
        underlying_price += self.underlying_adjustment

        self.theo_price, delta, gamma, theta, vega = self.calculate_greeks(
            underlying_price,
            self.strike_price,
            self.interest_rate,
            self.time_to_expiry,
            self.pricing_impv,
            self.option_type
        )

        self.theo_delta = delta * self.size
        self.theo_gamma = gamma * self.size
        self.theo_theta = theta * self.size
        self.theo_vega = vega * self.size

    def calculate_pos_greeks(self):
        """"""
        self.pos_value = self.theo_price * self.size * self.net_pos
        self.pos_delta = self.theo_delta * self.net_pos
        self.pos_gamma = self.theo_gamma * self.net_pos
        self.pos_theta = self.theo_theta * self.net_pos
        self.pos_vega = self.theo_vega * self.net_pos

    def update_tick(self, tick: TickData):
        """"""
        super().update_tick(tick)
        self.calculate_option_impv()

    def update_trade(self, trade: TradeData):
        """"""
        super().update_trade(trade)
        self.calculate_pos_greeks()

    def update_underlying_tick(self, underlying_adjustment: float):
        """"""
        self.underlying_adjustment = underlying_adjustment

        self.calculate_option_impv()
        self.calculate_theo_greeks()
        self.calculate_pos_greeks()

    def set_chain(self, chain: "ChainData"):
        """"""
        self.chain = chain

    def set_underlying(self, underlying: "UnderlyingData"):
        """"""
        self.underlying = underlying

    def set_interest_rate(self, interest_rate: float):
        """"""
        self.interest_rate = interest_rate

    def set_pricing_model(self, pricing_model: ModuleType):
        """"""
        self.calculate_greeks = pricing_model.calculate_greeks
        self.calculate_impv = pricing_model.calculate_impv
        self.calculate_price = pricing_model.calculate_price


class UnderlyingData(InstrumentData):
    """"""

    def __init__(self, contract: ContractData):
        """"""
        super().__init__(contract)

        self.theo_delta: float = 0
        self.pos_delta: float = 0
        self.chains: Dict[str: ChainData] = {}

    def add_chain(self, chain: "ChainData"):
        """"""
        self.chains[chain.chain_symbol] = chain

    def update_tick(self, tick: TickData):
        """"""
        super().update_tick(tick)

        self.theo_delta = self.size * self.mid_price / 100
        for chain in self.chains.values():
            chain.update_underlying_tick()

        self.calculate_pos_greeks()

    def update_trade(self, trade: TradeData):
        """"""
        super().update_trade(trade)

        self.calculate_pos_greeks()

    def calculate_pos_greeks(self):
        """"""
        self.pos_delta = self.theo_delta * self.net_pos


class ChainData:
    """"""

    def __init__(self, chain_symbol: str):
        """"""
        self.chain_symbol: str = chain_symbol

        self.long_pos: int = 0
        self.short_pos: int = 0
        self.net_pos: int = 0

        self.pos_value: float = 0
        self.pos_delta: float = 0
        self.pos_gamma: float = 0
        self.pos_theta: float = 0
        self.pos_vega: float = 0

        self.underlying: UnderlyingData = None

        self.options: Dict[str, OptionData] = {}
        self.calls: Dict[float, OptionData] = {}
        self.puts: Dict[float, OptionData] = {}

        self.portfolio: PortfolioData = None

        self.indexes: List[float] = []
        self.atm_price: float = 0
        self.atm_index: str = ""
        self.underlying_adjustment: float = 0
        self.days_to_expiry: int = 0

    def add_option(self, option: OptionData):
        """"""
        self.options[option.vt_symbol] = option

        if option.option_type > 0:
            self.calls[option.chain_index] = option
        else:
            self.puts[option.chain_index] = option

        option.set_chain(self)

        if option.chain_index not in self.indexes:
            self.indexes.append(option.chain_index)
            self.indexes.sort()

        self.days_to_expiry = option.days_to_expiry

    def calculate_pos_greeks(self):
        """"""
        # Clear data
        self.long_pos = 0
        self.short_pos = 0
        self.net_pos = 0
        self.pos_value = 0
        self.pos_delta = 0
        self.pos_gamma = 0
        self.pos_theta = 0
        self.pos_vega = 0

        # Sum all value
        for option in self.options.values():
            if option.net_pos:
                self.long_pos += option.long_pos
                self.short_pos += option.short_pos
                self.pos_value += option.pos_value
                self.pos_delta += option.pos_delta
                self.pos_gamma += option.pos_gamma
                self.pos_theta += option.pos_theta
                self.pos_vega += option.pos_vega

        self.net_pos = self.long_pos - self.short_pos

    def update_tick(self, tick: TickData):
        """"""
        option = self.options[tick.vt_symbol]
        option.update_tick(tick)

    def update_underlying_tick(self):
        """"""
        for option in self.options.values():
            option.update_underlying_tick(self.underlying_adjustment)

        self.calculate_pos_greeks()

    def update_trade(self, trade: TradeData):
        """"""
        option = self.options[trade.vt_symbol]

        # Deduct old option pos greeks
        self.long_pos -= option.long_pos
        self.short_pos -= option.short_pos
        self.pos_value -= option.pos_value
        self.pos_delta -= option.pos_delta
        self.pos_gamma -= option.pos_gamma
        self.pos_theta -= option.pos_theta
        self.pos_vega -= option.pos_vega

        # Calculate new option pos greeks
        option.update_trade(trade)

        # Add new option pos greeks
        self.long_pos += option.long_pos
        self.short_pos += option.short_pos
        self.pos_value += option.pos_value
        self.pos_delta += option.pos_delta
        self.pos_gamma += option.pos_gamma
        self.pos_theta += option.pos_theta
        self.pos_vega += option.pos_vega

        self.net_pos = self.long_pos - self.short_pos

    def set_underlying(self, underlying: "UnderlyingData"):
        """"""
        underlying.add_chain(self)
        self.underlying = underlying

        for option in self.options.values():
            option.set_underlying(underlying)

    def set_interest_rate(self, interest_rate: float):
        """"""
        for option in self.options.values():
            option.set_interest_rate(interest_rate)

    def set_pricing_model(self, pricing_model: ModuleType):
        """"""
        for option in self.options.values():
            option.set_pricing_model(pricing_model)

    def set_portfolio(self, portfolio: "PortfolioData"):
        """"""
        for option in self.options:
            option.set_portfolio(portfolio)

    def calculate_atm_price(self):
        """"""
        underlying_price = self.underlying.mid_price

        atm_distance = 0
        atm_price = 0

        for call in self.calls.values():
            price_distance = abs(underlying_price - call.strike_price)

            if not atm_distance or price_distance < atm_distance:
                atm_distance = price_distance
                atm_price = call.strike_price

        self.atm_price = atm_price
        self.atm_index = call.chain_index

    def calculate_underlying_adjustment(self):
        """"""
        if not self.atm_price:
            return

        atm_call = self.calls[self.atm_index]
        atm_put = self.puts[self.atm_index]

        synthetic_price = atm_call.mid_price - atm_put.mid_price + self.atm_price
        self.underlying_adjustment = synthetic_price - self.underlying.mid_price


class PortfolioData:

    def __init__(self, name: str):
        """"""
        self.name: str = name

        self.long_pos: int = 0
        self.short_pos: int = 0
        self.net_pos: int = 0

        self.pos_delta: float = 0
        self.pos_gamma: float = 0
        self.pos_theta: float = 0
        self.pos_vega: float = 0

        # All instrument
        self._options: Dict[str, OptionData] = {}
        self._chains: Dict[str, ChainData] = {}

        # Active instrument
        self.options: Dict[str, OptionData] = {}
        self.chains: Dict[str, ChainData] = {}
        self.underlyings: Dict[str, UnderlyingData] = {}

    def calculate_pos_greeks(self):
        """"""
        self.long_pos = 0
        self.short_pos = 0
        self.net_pos = 0

        self.pos_value = 0
        self.pos_delta = 0
        self.pos_gamma = 0
        self.pos_theta = 0
        self.pos_vega = 0

        for underlying in self.underlyings.values():
            self.pos_delta += underlying.pos_delta

        for chain in self.chains.values():
            self.long_pos += chain.long_pos
            self.short_pos += chain.short_pos
            self.pos_value += chain.pos_value
            self.pos_delta += chain.pos_delta
            self.pos_gamma += chain.pos_gamma
            self.pos_theta += chain.pos_theta
            self.pos_vega += chain.pos_vega

        self.net_pos = self.long_pos - self.short_pos

    def update_tick(self, tick: TickData):
        """"""
        if tick.vt_symbol in self.options:
            option = self.options[tick.vt_symbol]
            chain = option.chain
            chain.update_tick(tick)
            self.calculate_pos_greeks()
        elif tick.vt_symbol in self.underlyings:
            underlying = self.underlyings[tick.vt_symbol]
            underlying.update_tick(tick)
            self.calculate_pos_greeks()

    def update_trade(self, trade: TradeData):
        """"""
        if trade.vt_symbol in self.options:
            option = self.options[trade.vt_symbol]
            chain = option.chain
            chain.update_trade(trade)
            self.calculate_pos_greeks()
        elif trade.vt_symbol in self.underlyings:
            underlying = self.underlyings[trade.vt_symbol]
            underlying.update_trade(trade)
            self.calculate_pos_greeks()

    def set_interest_rate(self, interest_rate: float):
        """"""
        for chain in self.chains.values():
            chain.set_interest_rate(interest_rate)

    def set_pricing_model(self, pricing_model: ModuleType):
        """"""
        for chain in self.chains.values():
            chain.set_pricing_model(pricing_model)

    def set_chain_underlying(self, chain_symbol: str, contract: ContractData):
        """"""
        underlying = self.underlyings.get(contract.vt_symbol, None)
        if not underlying:
            underlying = UnderlyingData(contract)
            underlying.set_portfolio(self)
            self.underlyings[contract.vt_symbol] = underlying

        chain = self.get_chain(chain_symbol)
        chain.set_underlying(underlying)

        # Add to active dict
        self.chains[chain_symbol] = chain

        for option in chain.options.values():
            self.options[option.vt_symbol] = option

    def get_chain(self, chain_symbol: str) -> ChainData:
        """"""
        chain = self._chains.get(chain_symbol, None)

        if not chain:
            chain = ChainData(chain_symbol)
            chain.set_portfolio(self)
            self._chains[chain_symbol] = chain

        return chain

    def add_option(self, contract: ContractData):
        """"""
        option = OptionData(contract)
        option.set_portfolio(self)
        self._options[contract.vt_symbol] = option

        exchange_name = contract.exchange.value
        chain_symbol: str = f"{contract.option_underlying}.{exchange_name}"

        chain = self.get_chain(chain_symbol)
        chain.add_option(option)

    def calculate_atm_price(self):
        """"""
        for chain in self.chains.values():
            chain.calculate_atm_price()
