import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class GPIODevice(ABC):
    """Abstract base class for GPIO device interaction."""

    @abstractmethod
    def read_pin(self, pin: int) -> int:
        """Read the value of a GPIO pin.

        Args:
            pin: The GPIO pin number (BCM numbering).

        Returns:
            The pin value (0 or 1).
        """

    @abstractmethod
    def write_pin(self, pin: int, value: int) -> None:
        """Write a value to a GPIO pin.

        Args:
            pin: The GPIO pin number (BCM numbering).
            value: The value to set (0 or 1).
        """

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up GPIO resources."""


class RealGPIODevice(GPIODevice):
    """GPIO device implementation using RPi.GPIO."""

    def __init__(self) -> None:
        try:
            import RPi.GPIO as GPIO  # type: ignore[import-untyped]

            self._gpio = GPIO
            self._gpio.setmode(self._gpio.BCM)
            self._gpio.setwarnings(False)
            logger.info("RPi.GPIO initialized in BCM mode")
        except (ImportError, RuntimeError) as exc:
            logger.error("Failed to initialize RPi.GPIO: %s", exc)
            raise

    def read_pin(self, pin: int) -> int:
        self._gpio.setup(pin, self._gpio.IN)
        value = self._gpio.input(pin)
        logger.debug("Read pin %d: value=%d", pin, value)
        return int(value)

    def write_pin(self, pin: int, value: int) -> None:
        self._gpio.setup(pin, self._gpio.OUT)
        self._gpio.output(pin, value)
        logger.debug("Write pin %d: value=%d", pin, value)

    def cleanup(self) -> None:
        self._gpio.cleanup()
        logger.info("GPIO cleanup completed")


class MockGPIODevice(GPIODevice):
    """Mock GPIO device for development and testing without a Raspberry Pi."""

    def __init__(self) -> None:
        self._pins: dict[int, int] = {}
        logger.info("MockGPIODevice initialized (no real GPIO available)")

    def read_pin(self, pin: int) -> int:
        value = self._pins.get(pin, 0)
        logger.debug("Mock read pin %d: value=%d", pin, value)
        return value

    def write_pin(self, pin: int, value: int) -> None:
        self._pins[pin] = value
        logger.debug("Mock write pin %d: value=%d", pin, value)

    def cleanup(self) -> None:
        self._pins.clear()
        logger.info("Mock GPIO cleanup completed")


def get_gpio_device(enabled: bool) -> GPIODevice:
    """Factory function to create the appropriate GPIO device.

    Args:
        enabled: If True, attempts to use real RPi.GPIO.
                 If False or if RPi.GPIO is unavailable, uses MockGPIODevice.

    Returns:
        A GPIODevice instance.
    """
    if enabled:
        try:
            return RealGPIODevice()
        except (ImportError, RuntimeError):
            logger.warning(
                "GPIO_ENABLED is True but RPi.GPIO is not available. "
                "Falling back to MockGPIODevice."
            )
            return MockGPIODevice()
    return MockGPIODevice()
