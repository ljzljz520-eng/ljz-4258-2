from enum import StrEnum


class NodeType(StrEnum):
    PROCESS = "process"
    TANK = "tank"
    SOURCE = "source"
    SINK = "sink"


class SegmentKind(StrEnum):
    CREAM = "cream"
    SKIM = "skim"
    STANDARDIZED = "standardized"
    CROSS_BATCH = "cross_batch"
    OTHER = "other"


class BatchStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    FROZEN = "frozen"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNDERDETERMINED = "underdetermined"
    SUPERSEDED = "superseded"


class MetricKind(StrEnum):
    VOLUME_FLOW = "volume_flow"
    MASS_FLOW = "mass_flow"
    DENSITY = "density"
    FAT_FRACTION = "fat_fraction"
    SOLIDS_FRACTION = "solids_fraction"
    MASS = "mass"
    FAT_MASS = "fat_mass"


class UnitSystem(StrEnum):
    SI = "si"
    CONVENIENCE = "convenience"


class Basis(StrEnum):
    WET = "wet"
    DRY = "dry"


class UncertaintyType(StrEnum):
    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    STDDEV = "stddev"
    EXPANDED_95 = "expanded_95"
