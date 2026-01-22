"""Price conversion and rounding logic."""

from decimal import ROUND_CEILING, Decimal

import structlog

from src.autopost.models import Product, RawProduct

logger = structlog.get_logger(__name__)

# "Pretty" price values for rounding (in KGS)
# Prices are rounded UP to the nearest value in this list
PRETTY_PRICES: list[int] = [
    # Under 100
    29, 49, 59, 79, 99,
    # 100-300
    149, 199, 249, 299,
    # 300-500
    349, 399, 449, 499,
    # 500-1000
    599, 699, 799, 899, 999,
    # 1000-2000
    1199, 1299, 1499, 1699, 1999,
    # 2000-4000
    2499, 2999, 3499, 3999,
    # 4000-7000
    4499, 4999, 5999, 6999,
    # 7000-10000
    7999, 8999, 9999,
    # 10000-20000
    11999, 12999, 14999, 16999, 19999,
    # 20000-50000
    24999, 29999, 34999, 39999, 49999,
]

# Maximum pretty price in the list
MAX_PRETTY_PRICE = PRETTY_PRICES[-1]


class PriceConverter:
    """Converts prices from CNY to KGS with pretty rounding.

    Handles currency conversion and rounds prices to psychologically
    appealing values (e.g., 299, 499, 999) that are more attractive
    to customers.

    The rounding is always UP to ensure the business doesn't lose money.
    """

    @staticmethod
    def convert(price_cny: Decimal, rate: Decimal) -> Decimal:
        """Convert price from CNY to KGS.

        Args:
            price_cny: Price in Chinese Yuan.
            rate: Exchange rate (CNY to KGS).

        Returns:
            Price in Kyrgyz Som (not rounded).
        """
        price_kgs = price_cny * rate
        return price_kgs.quantize(Decimal("0.01"), rounding=ROUND_CEILING)

    @staticmethod
    def round_to_pretty(price: Decimal) -> Decimal:
        """Round price up to the nearest "pretty" value.

        Pretty values are psychologically appealing prices like
        29, 99, 299, 499, 999, etc.

        Args:
            price: Price to round.

        Returns:
            Nearest pretty price >= input price.
        """
        price_int = int(price.to_integral_value(rounding=ROUND_CEILING))

        # Handle very small prices
        if price_int <= 0:
            return Decimal(PRETTY_PRICES[0])

        # Find the smallest pretty price >= price_int
        for pretty in PRETTY_PRICES:
            if pretty >= price_int:
                return Decimal(pretty)

        # For prices above MAX_PRETTY_PRICE, round to nearest X999
        # e.g., 52000 -> 52999, 123000 -> 123999
        thousands = (price_int // 1000) + 1
        return Decimal(thousands * 1000 - 1)

    @classmethod
    def convert_and_round(cls, price_cny: Decimal, rate: Decimal) -> Decimal:
        """Convert CNY to KGS and round to pretty price.

        Combines conversion and rounding in one step.

        Args:
            price_cny: Price in Chinese Yuan.
            rate: Exchange rate (CNY to KGS).

        Returns:
            Pretty-rounded price in Kyrgyz Som.
        """
        raw_price = cls.convert(price_cny, rate)
        pretty_price = cls.round_to_pretty(raw_price)

        logger.debug(
            "price_converted",
            price_cny=float(price_cny),
            rate=float(rate),
            raw_kgs=float(raw_price),
            pretty_kgs=float(pretty_price),
        )

        return pretty_price

    @classmethod
    def convert_product(cls, raw: RawProduct, rate: Decimal) -> Product:
        """Convert RawProduct to Product with KGS price.

        Creates a Product instance with both CNY and KGS prices,
        where KGS price is rounded to a pretty value.

        Args:
            raw: Raw product from Pinduoduo API.
            rate: Exchange rate (CNY to KGS).

        Returns:
            Product with both prices set.
        """
        price_kgs = cls.convert_and_round(raw.price_cny, rate)

        logger.info(
            "product_price_converted",
            product_id=raw.id,
            price_cny=float(raw.price_cny),
            price_kgs=float(price_kgs),
        )

        return Product.from_raw(raw, price_kgs)

    @classmethod
    def convert_products(
        cls, products: list[RawProduct], rate: Decimal
    ) -> list[Product]:
        """Convert multiple RawProducts to Products with KGS prices.

        Args:
            products: List of raw products from Pinduoduo API.
            rate: Exchange rate (CNY to KGS).

        Returns:
            List of Products with converted prices.
        """
        converted = [cls.convert_product(p, rate) for p in products]

        logger.info(
            "products_converted",
            count=len(converted),
            rate=float(rate),
        )

        return converted


def get_pretty_prices() -> list[int]:
    """Get the list of pretty prices.

    Returns:
        List of pretty price values.
    """
    return PRETTY_PRICES.copy()
