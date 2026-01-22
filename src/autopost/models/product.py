"""Product models for Tulpar Express."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RawProduct(BaseModel):
    """Raw product data from Pinduoduo/Taobao API.

    Represents a product as returned from the RapidAPI endpoint
    before any processing or filtering.
    """

    id: str = Field(description="Unique product identifier")
    title: str = Field(description="Product title/name")
    price_cny: Decimal = Field(gt=0, description="Price in Chinese Yuan (CNY)")
    image_url: str = Field(description="URL to product image")
    rating: float = Field(ge=0, le=5, description="Product rating (0-5 stars)")
    discount: int = Field(ge=0, le=100, description="Discount percentage (0-100)")
    sales_count: int = Field(ge=0, description="Number of sales")
    source: str = Field(default="pinduoduo", description="Product source: pinduoduo or taobao")

    model_config = ConfigDict(
        frozen=True,
        str_strip_whitespace=True,
    )


class Product(BaseModel):
    """Processed product with converted price.

    Extends RawProduct with KGS price after currency conversion.
    Used for display and publishing.
    """

    id: str = Field(description="Unique product identifier")
    title: str = Field(description="Product title/name")
    price_cny: Decimal = Field(gt=0, description="Original price in CNY")
    price_kgs: Decimal = Field(gt=0, description="Converted price in KGS")
    old_price_kgs: Decimal = Field(default=Decimal("0"), description="Marketing old price in KGS")
    image_url: str = Field(description="URL to product image")
    rating: float = Field(ge=0, le=5, description="Product rating (0-5 stars)")
    discount: int = Field(ge=0, le=100, description="Discount percentage (0-100)")
    sales_count: int = Field(ge=0, description="Number of sales")
    source: str = Field(default="pinduoduo", description="Product source: pinduoduo or taobao")

    model_config = ConfigDict(
        from_attributes=True,
    )

    @classmethod
    def from_raw(cls, raw: RawProduct, price_kgs: Decimal) -> "Product":
        """Create Product from RawProduct with converted price.

        Args:
            raw: Raw product data from API.
            price_kgs: Converted price in Kyrgyz Som.

        Returns:
            Product instance with both CNY and KGS prices.
        """
        return cls(
            id=raw.id,
            title=raw.title,
            price_cny=raw.price_cny,
            price_kgs=price_kgs,
            image_url=raw.image_url,
            rating=raw.rating,
            discount=raw.discount,
            sales_count=raw.sales_count,
            source=raw.source,
        )
