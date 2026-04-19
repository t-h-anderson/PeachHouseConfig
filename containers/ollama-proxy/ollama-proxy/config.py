import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.toml"


@dataclass(frozen=True)
class DesktopConfig:
    ip: str
    mac: str


@dataclass(frozen=True)
class PortConfig:
    proxyPort: int
    ollamaPort: int
    agentPort: int


@dataclass(frozen=True)
class TimeoutConfig:
    wakeTimeoutSeconds: int
    wakePollIntervalSeconds: int
    agentRequestTimeoutSeconds: int


@dataclass(frozen=True)
class ProxyConfig:
    desktop: DesktopConfig
    ports: PortConfig
    timeouts: TimeoutConfig

    @property
    def ollamaBaseUrl(self) -> str:
        return f"http://{self.desktop.ip}:{self.ports.ollamaPort}"

    @property
    def agentBaseUrl(self) -> str:
        return f"http://{self.desktop.ip}:{self.ports.agentPort}"


def loadConfig(path: Path = CONFIG_PATH) -> ProxyConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return ProxyConfig(
        desktop=DesktopConfig(**raw["desktop"]),
        ports=PortConfig(**raw["ports"]),
        timeouts=TimeoutConfig(**raw["timeouts"]),
    )


config = loadConfig()
