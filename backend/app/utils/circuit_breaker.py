"""
Circuit Breaker Pattern.

WHY THIS EXISTS:
─────────────────
Without circuit breaker:
  RabbitMQ goes down
  → Every publish attempt waits for timeout (5-30 seconds)
  → Requests pile up waiting
  → Thread pool exhausted
  → Entire API becomes unresponsive
  → One dependency failure cascades to total system failure

With circuit breaker:
  RabbitMQ goes down
  → First few failures detected
  → Circuit OPENS — subsequent calls fail immediately (no waiting)
  → API stays responsive, just without async order processing
  → After cooldown, circuit tests if RabbitMQ recovered
  → If recovered → circuit CLOSES, normal operation resumes

STATES:
────────
CLOSED:    Normal operation. Requests flow through.
           Failure counter incremented on each failure.
           When failures >= threshold → transition to OPEN.

OPEN:      Fast fail. No requests sent to dependency.
           After cooldown_seconds → transition to HALF_OPEN.

HALF_OPEN: One test request allowed through.
           If succeeds → transition to CLOSED (recovered).
           If fails    → transition back to OPEN (still down).

STORAGE:
─────────
State stored in Redis so all API server instances share
the same circuit breaker state. If one server detects
RabbitMQ is down, all servers immediately open their circuit.
"""

import time
from enum import Enum

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class CircuitState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Distributed circuit breaker backed by Redis.
    All instances share state — one detection protects all servers.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: int  = 30,
        success_threshold: int = 2,
    ):
        self.redis             = redis
        self.name              = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds  = cooldown_seconds
        self.success_threshold = success_threshold

    # ── Redis Keys ────────────────────────────────────────────────────────────

    def _state_key(self) -> str:
        return f"circuit:{self.name}:state"

    def _failure_count_key(self) -> str:
        return f"circuit:{self.name}:failures"

    def _success_count_key(self) -> str:
        return f"circuit:{self.name}:successes"

    def _opened_at_key(self) -> str:
        return f"circuit:{self.name}:opened_at"

    # ── State Management ──────────────────────────────────────────────────────

    async def get_state(self) -> CircuitState:
        state = await self.redis.get(self._state_key())
        if state is None:
            return CircuitState.CLOSED
        return CircuitState(state)

    async def _set_state(self, state: CircuitState) -> None:
        await self.redis.set(self._state_key(), state.value)

    # ── Core Logic ────────────────────────────────────────────────────────────

    async def call(self, func, *args, **kwargs):
        """
        Wraps a function call with circuit breaker protection.

        Usage:
            result = await circuit_breaker.call(
                publish_to_rabbitmq, message
            )
        """
        state = await self.get_state()

        # ── OPEN: Check if cooldown has passed ────────────────────────────────
        if state == CircuitState.OPEN:
            opened_at = await self.redis.get(self._opened_at_key())
            if opened_at:
                elapsed = time.time() - float(opened_at)
                if elapsed >= self.cooldown_seconds:
                    # Cooldown passed — try half-open
                    await self._set_state(CircuitState.HALF_OPEN)
                    logger.info(
                        "Circuit breaker transitioning to HALF_OPEN",
                        name=self.name,
                        elapsed_seconds=round(elapsed, 1),
                    )
                else:
                    # Still in cooldown — fail fast
                    raise CircuitOpenError(
                        f"Circuit {self.name} is OPEN. "
                        f"Retry in {self.cooldown_seconds - elapsed:.0f}s"
                    )
            else:
                raise CircuitOpenError(f"Circuit {self.name} is OPEN")

        # ── CLOSED or HALF_OPEN: Attempt the call ─────────────────────────────
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result

        except CircuitOpenError:
            raise

        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self) -> None:
        state = await self.get_state()

        if state == CircuitState.HALF_OPEN:
            # Increment success counter
            count = await self.redis.incr(self._success_count_key())
            await self.redis.expire(self._success_count_key(), 60)

            if count >= self.success_threshold:
                # Enough successes — close the circuit
                await self._set_state(CircuitState.CLOSED)
                await self.redis.delete(self._failure_count_key())
                await self.redis.delete(self._success_count_key())
                await self.redis.delete(self._opened_at_key())

                logger.info(
                    "Circuit breaker CLOSED — service recovered",
                    name=self.name,
                )

        elif state == CircuitState.CLOSED:
            # Reset failure counter on success
            await self.redis.delete(self._failure_count_key())

    async def _on_failure(self) -> None:
        state = await self.get_state()

        if state == CircuitState.HALF_OPEN:
            # Failed in half-open — reopen immediately
            await self._open_circuit()
            return

        # Increment failure counter
        count = await self.redis.incr(self._failure_count_key())
        await self.redis.expire(self._failure_count_key(), 60)

        logger.warning(
            "Circuit breaker recorded failure",
            name=self.name,
            failure_count=count,
            threshold=self.failure_threshold,
        )

        if count >= self.failure_threshold:
            await self._open_circuit()

    async def _open_circuit(self) -> None:
        await self._set_state(CircuitState.OPEN)
        await self.redis.set(self._opened_at_key(), str(time.time()))
        await self.redis.delete(self._failure_count_key())

        logger.error(
            "Circuit breaker OPENED — failing fast",
            name=self.name,
            cooldown_seconds=self.cooldown_seconds,
        )

    async def get_status(self) -> dict:
        """Returns full circuit breaker status for monitoring."""
        state      = await self.get_state()
        failures   = await self.redis.get(self._failure_count_key())
        opened_at  = await self.redis.get(self._opened_at_key())

        return {
            "name":            self.name,
            "state":           state.value,
            "failure_count":   int(failures or 0),
            "threshold":       self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "opened_at":       opened_at,
        }


class CircuitOpenError(Exception):
    """Raised when circuit is open and call is rejected."""
    pass