"""OpenAI service for generating marketing content via RapidAPI."""

from __future__ import annotations

import random
from typing import Any

import httpx
from deep_translator import GoogleTranslator

from src.autopost.config import settings
from src.autopost.exceptions import ServiceError
from src.autopost.models import Product
from src.autopost.services.base import BaseService, ServiceResult

# OpenRouter API endpoint (unified access to GPT-4, Claude, etc.)
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# System prompt for generating product descriptions
SYSTEM_PROMPT = """Ты — переводчик и описатель товаров для Telegram канала.
Твоя задача — ПЕРЕВЕСТИ название товара на русский и написать понятное описание.

ВАЖНО:
1. ПЕРЕВЕДИ название товара на русский язык
2. Опиши ЧТО ЭТО за товар простыми словами
3. ОБЯЗАТЕЛЬНО укажи примерные характеристики:
   - Вес (примерный, исходя из типа товара)
   - Размеры (примерные, исходя из типа товара)
   - Материал
4. НЕ пиши цены - они добавятся автоматически

ФОРМАТ ОТВЕТА:
🛒 [Название на русском]

[Описание товара 2-3 предложения]

📏 Характеристики:
• Размер: [примерный размер, например "25×15×10 см"]
• Вес: [примерный вес, например "~300 г"]
• Материал: [материал]
• [другие важные характеристики]

📩 Для заказа: @{contact_username}

ПРИМЕР для "Kitchen seasoning storage rack chopstick knife rack":
🛒 Кухонный органайзер для специй и ножей

Многофункциональная полка-органайзер для кухни. Позволяет компактно хранить баночки со специями, ножи и кухонные принадлежности.

📏 Характеристики:
• Размер: ~35×20×15 см
• Вес: ~800 г
• Материал: нержавеющая сталь
• Несколько уровней хранения

📩 Для заказа: @{contact_username}

ЗАПРЕЩЕНО:
- Оставлять английские/китайские слова
- Писать "надёжный продавец", "хит продаж", "отличное качество"
- Писать цены"""

# Fallback templates (without prices - prices added separately in pipeline)
# Used when AI API is unavailable
FALLBACK_TEMPLATES = [
    """🛒 {title}

📩 Для заказа: @{contact_username}""",
]


class OpenAIService(BaseService):
    """Service for generating marketing content via RapidAPI GPT.

    Generates selling descriptions for products in Russian language
    with emphasis on price comparison (было/стало format).
    Falls back to template-based generation if API is unavailable.

    Attributes:
        model: Model to use (default: gpt-4o).
        timeout: Request timeout in seconds (default: 30).
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        """Initialize OpenAI service.

        Args:
            client: Optional httpx.AsyncClient for HTTP requests.
            model: Model to use (defaults to settings.openai_model).
            timeout: Request timeout in seconds (defaults to settings.openai_timeout).
        """
        super().__init__(client)
        self.model = model or settings.openai_model
        self.timeout = timeout or settings.openai_timeout

    def _get_headers(self) -> dict[str, str]:
        """Get headers for OpenRouter API requests.

        Returns:
            Dictionary with Authorization header.
        """
        return {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }

    def _build_user_prompt(self, product: Product) -> str:
        """Build user prompt for product description generation.

        Args:
            product: Product to generate description for.

        Returns:
            Formatted prompt string.
        """
        old_price = int(product.old_price_kgs) if product.old_price_kgs > 0 else int(float(product.price_kgs) * 1.4)
        new_price = int(product.price_kgs)
        savings = old_price - new_price
        discount = product.discount if product.discount > 0 else 30

        return f"""Товар: {product.title}

ЦЕНЫ:
- Было: {old_price} сом
- Стало: {new_price} сом
- Экономия: {savings} сом
- Скидка: {discount}%

Напиши короткое цепляющее описание с акцентом на выгоду."""

    async def generate_description(
        self, product: Product
    ) -> ServiceResult[str]:
        """Generate selling description for a product.

        Calls RapidAPI GPT to generate a marketing description in Russian
        with "было/стало" price comparison format.
        Falls back to template-based text if API fails.

        Args:
            product: Product to generate description for.

        Returns:
            ServiceResult containing generated description or fallback text.
        """
        self.logger.info(
            "generating_description",
            product_id=product.id,
            product_title=product.title[:50],
        )

        try:
            description = await self._call_gpt_api(product)

            self.logger.info(
                "description_generated",
                product_id=product.id,
                word_count=len(description.split()),
            )

            return ServiceResult.ok(description)

        except (ServiceError, httpx.HTTPStatusError, httpx.TimeoutException) as e:
            self.logger.warning(
                "gpt_api_failed",
                product_id=product.id,
                error=str(e),
                fallback="template",
            )
            # Use fallback template
            fallback_text = self._generate_fallback(product)
            return ServiceResult.ok(fallback_text)

        except Exception as e:
            self.logger.error(
                "unexpected_error",
                product_id=product.id,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Still provide fallback on unexpected errors
            fallback_text = self._generate_fallback(product)
            return ServiceResult.ok(fallback_text)

    async def _call_gpt_api(self, product: Product) -> str:
        """Make API call to RapidAPI GPT.

        Args:
            product: Product to generate description for.

        Returns:
            Generated description text.

        Raises:
            ServiceError: If API request fails.
            httpx.TimeoutException: If request times out.
        """
        user_prompt = self._build_user_prompt(product)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.format(contact_username=settings.contact_username)},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 200,
            "temperature": 0.7,
        }

        self.logger.debug(
            "calling_gpt_api",
            model=self.model,
            product_id=product.id,
        )

        # Use custom timeout (30 sec as per NFR3)
        timeout = httpx.Timeout(
            connect=5.0,
            read=float(self.timeout),
            write=10.0,
            pool=5.0,
        )

        response = await self.client.post(
            OPENROUTER_API_URL,
            headers=self._get_headers(),
            json=payload,
            timeout=timeout,
        )

        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> str:
        """Parse GPT API response.

        Args:
            data: JSON response from GPT API.

        Returns:
            Generated text content.

        Raises:
            ServiceError: If response format is unexpected.
        """
        try:
            choices = data.get("choices", [])
            if not choices:
                raise ServiceError(
                    message="Empty choices in GPT response",
                    service_name="OpenAIService",
                )

            message = choices[0].get("message", {})
            content = message.get("content", "").strip()

            if not content:
                raise ServiceError(
                    message="Empty content in GPT response",
                    service_name="OpenAIService",
                )

            return content

        except (KeyError, IndexError, TypeError) as e:
            raise ServiceError(
                message=f"Failed to parse GPT response: {e}",
                service_name="OpenAIService",
                original_error=e,
            ) from e

    def _generate_fallback(self, product: Product) -> str:
        """Generate fallback description using template.

        Used when GPT API is unavailable.
        Translates title to Russian using Google Translate.
        Prices are added separately in the pipeline.

        Args:
            product: Product to generate description for.

        Returns:
            Template-based description (prices added separately).
        """
        template = random.choice(FALLBACK_TEMPLATES)

        # Translate title to Russian using Google Translate
        try:
            translator = GoogleTranslator(source='auto', target='ru')
            translated_title = translator.translate(product.title[:100])
            # Capitalize first letter
            if translated_title:
                translated_title = translated_title[0].upper() + translated_title[1:]
        except Exception:
            # If translation fails, use original title
            translated_title = product.title[:80]

        return template.format(
            title=translated_title,
            contact_username=settings.contact_username,
        )

    async def generate_descriptions_batch(
        self, products: list[Product]
    ) -> list[ServiceResult[str]]:
        """Generate descriptions for multiple products.

        Processes products sequentially to respect API rate limits.

        Args:
            products: List of products to generate descriptions for.

        Returns:
            List of ServiceResult for each product.
        """
        results = []
        for product in products:
            result = await self.generate_description(product)
            results.append(result)
        return results
