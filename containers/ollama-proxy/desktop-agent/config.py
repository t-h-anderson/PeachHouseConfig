import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.toml"


@dataclass(frozen=True)
class PortConfig:
    agentPort: int


@dataclass(frozen=True)
class TimeoutConfig:
    idleThresholdSeconds: int
    shutdownWarningSeconds: int
    activityStalenessSeconds: int


@dataclass(frozen=True)
class MonitorConfig:
    pollIntervalSeconds: int


@dataclass(frozen=True)
class PathConfig:
    stateFile: Path


@dataclass(frozen=True)
class AgentConfig:
    ports: PortConfig
    timeouts: TimeoutConfig
    monitor: MonitorConfig
    paths: PathConfig


def loadConfig(path: Path = CONFIG_PATH) -> AgentConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return AgentConfig(
        ports=PortConfig(**raw["ports"]),
        timeouts=TimeoutConfig(**raw["timeouts"]),
        monitor=MonitorConfig(**raw["monitor"]),
        paths=PathConfig(stateFile=Path(raw["paths"]["stateFile"])),
    )


config = loadConfig()
