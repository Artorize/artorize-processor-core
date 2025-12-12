"""HTTP client for sending completion callbacks to Router."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


class CallbackClient:
    """HTTP client for sending callbacks to Router with retry logic."""

    def __init__(
        self,
        timeout: float = 10.0,
        retry_attempts: int = 3,
        retry_delay: float = 2.0,
    ):
        """
        Initialize callback client.

        Args:
            timeout: HTTP request timeout in seconds
            retry_attempts: Number of retry attempts on failure
            retry_delay: Delay between retries in seconds
        """
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay

    async def send_completion_callback(
        self,
        callback_url: str,
        auth_token: str,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Send processing completion callback with retry logic.

        Args:
            callback_url: URL to send callback to
            auth_token: Authorization token (e.g., "Bearer secret-token")
            payload: JSON payload to send

        Returns:
            True if callback successful, False otherwise
        """
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
        }

        for attempt in range(self.retry_attempts):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        callback_url,
                        json=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    if response.status_code == 200:
                        logger.info(f"Callback successful for job {payload.get('job_id')}")
                        return True

                    logger.warning(
                        f"Callback failed with status {response.status_code} "
                        f"for job {payload.get('job_id')} (attempt {attempt + 1}/{self.retry_attempts})"
                    )

            except (httpx.TimeoutError, httpx.NetworkError) as e:
                logger.error(
                    f"Callback network error for job {payload.get('job_id')}: {e} "
                    f"(attempt {attempt + 1}/{self.retry_attempts})"
                )
                if attempt == self.retry_attempts - 1:
                    # Last attempt failed
                    await self._store_failed_callback(payload)
                    return False
                await asyncio.sleep(self.retry_delay)

            except Exception as e:
                logger.error(f"Unexpected callback error for job {payload.get('job_id')}: {e}")
                await self._store_failed_callback(payload)
                return False

        return False

    async def send_progress_callback(
        self,
        callback_url: str,
        auth_token: str,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Send processing progress callback with retry logic.

        Args:
            callback_url: URL to send callback to
            auth_token: Authorization token (e.g., "Bearer secret-token")
            payload: JSON payload with progress information

        Returns:
            True if callback successful, False otherwise
        """
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
        }

        for attempt in range(self.retry_attempts):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        callback_url,
                        json=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    if response.status_code == 200:
                        logger.info(
                            f"Progress callback successful for job {payload.get('job_id')} "
                            f"(step {payload.get('step_number')}/{payload.get('total_steps')})"
                        )
                        return True

                    logger.warning(
                        f"Progress callback failed with status {response.status_code} "
                        f"for job {payload.get('job_id')} (attempt {attempt + 1}/{self.retry_attempts})"
                    )

            except (httpx.TimeoutError, httpx.NetworkError) as e:
                logger.error(
                    f"Progress callback network error for job {payload.get('job_id')}: {e} "
                    f"(attempt {attempt + 1}/{self.retry_attempts})"
                )
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay)

            except Exception as e:
                logger.error(f"Unexpected progress callback error for job {payload.get('job_id')}: {e}")
                return False

        return False

    async def _store_failed_callback(self, payload: Dict[str, Any]) -> None:
        """
        Store failed callback in dead letter queue.

        Args:
            payload: The callback payload that failed to send
        """
        # TODO: Implement dead letter queue (DLQ) storage
        # Could write to a file, database, or message queue
        logger.error(f"Failed callback stored to DLQ for job {payload.get('job_id')}")
        # For now, just log the failure
