from dataclasses import dataclass
try:
    from enum import StrEnum
except ImportError:
    # Fallback for Python < 3.11
    from enum import Enum
    class StrEnum(str, Enum):
        pass

try:
    from homeassistant.const import Platform
    # Use Platform enum for better compatibility
    PLATFORMS = [
        Platform.VACUUM,
        Platform.BUTTON,
        Platform.SENSOR,
        Platform.SWITCH,
        Platform.NUMBER,
        Platform.SELECT,
    ]
except ImportError:
    # Fallback if Platform enum is not available
    PLATFORMS = ["vacuum", "button", "sensor", "switch", "number", "select"]

DOMAIN = "eufy_robovac_s1_pro"

CONF_DEVICE_ID = "DEVICE_ID"
CONF_LOCAL_KEY = "LOCAL_KEY"
CONF_LOCAL_TUYA_CLIENT = "TUYA_CLIENT"

CONF_DISCOVERED_DEVICES = "DISCOVERED_DEVICES"
CONF_COORDINATOR = "COORDINATOR"


class RobovacDPs(StrEnum):
    ROBOVAC_2150_REMOTE_CONTROL_DPS_ID_131 = "131"
    ROBOVAC_AREA_CLEAN_ACTIVE_DPS_ID_117 = "117"
    ROBOVAC_AREA_CLEAN_DPS_ID_116 = "116"
    ROBOVAC_AREA_SET_DPS_ID_124 = "124"
    ROBOVAC_AUTO_RETURN_CLEAN_DPS_ID_156 = "156"
    ROBOVAC_BOOST_IQ_DPS_ID_118 = "118"
    ROBOVAC_CLEAN_MODE_DPS_ID_5 = "5"
    ROBOVAC_CLEAR_AREA_DPS_ID_110 = "110"
    ROBOVAC_CLEAR_TIME_DPS_ID_109 = "109"
    ROBOVAC_CLEAR_TOTAL_AREA_DPS_ID_120 = "120"
    ROBOVAC_CLEAR_TOTAL_TIME_DPS_ID_119 = "119"
    ROBOVAC_DIRECTION_DPS_ID_3 = "3"
    ROBOVAC_DO_NOT_DISTURB_DPS_ID_139 = "139"
    ROBOVAC_EDIT_ROOM_DPS_ID_141 = "141"
    ROBOVAC_ELECTRIC_DPS_ID_104 = "104"
    ROBOVAC_ERROR_ALARM_DPS_ID_106 = "106"
    ROBOVAC_FILETR_TM_DPS_ID_114 = "114"
    ROBOVAC_FIND_ROBOVAC_DPS_ID_103 = "103"
    ROBOVAC_G40_CHARING_TYPE = "143"
    ROBOVAC_G40_COLLECT_DUST = "147"
    ROBOVAC_G40_MOPPING_WATER = "144"
    ROBOVAC_G40_SCHEDULE_MOPPING_WATER = "145"
    ROBOVAC_GET_MAP_OR_PATH_DATA_DPS_ID_121 = "121"
    ROBOVAC_GO_HOME_DPS_ID_101 = "101"
    ROBOVAC_LANGUAGE_SET_DPS_ID_123 = "123"
    ROBOVAC_LOG_UPLOAD_DPS_ID_142 = "142"
    ROBOVAC_LOUDNESS_DPS_ID_111 = "111"
    ROBOVAC_MAIN_BSHTM_DPS_ID_113 = "113"
    ROBOVAC_MAP_MANAGER_DPS_ID_143 = "143"
    ROBOVAC_MAP_MANAGE_DPS_ID_146 = "146"
    ROBOVAC_MODE_STATUS_DPS_ID_15 = "15"
    ROBOVAC_MOP_DPS_ID_105 = "105"
    ROBOVAC_MOP_DPS_ID_129 = "129"
    ROBOVAC_NOT_DISTURB_DPS_ID_107 = "107"
    ROBOVAC_PAUSE_STAR_DPS_ID_122 = "122"
    ROBOVAC_PLAY_OR_PAUSE_DPS_ID = "1"
    ROBOVAC_PLAY_OR_PAUSE_DPS_ID_2 = "2"
    ROBOVAC_POS_DPS_ID_108 = "108"
    ROBOVAC_REMIND_ALARM_DPS_ID_137 = "137"
    ROBOVAC_REPLACE_DPS_ID_115 = "115"
    ROBOVAC_ROBOVAC_SPEED_DPS_ID_102 = "102"
    ROBOVAC_ROBOVAC_SPEED_DPS_ID_130 = "130"
    ROBOVAC_SAVE_MAP_DPS_ID_147 = "147"
    ROBOVAC_SENSOR_TM_DPS_ID_127 = "127"
    ROBOVAC_SETTING_DPS_ID_126 = "126"
    ROBOVAC_SIDE_BSHTM_DPS_ID_112 = "112"
    ROBOVAC_SMART_ROOMS_DPS_ID_140 = "140"
    ROBOVAC_VOICE_DEFAULT_SET_DPS_ID_128 = "128"
    ROBOVAC_VOICE_TYPE_SET_DPS_ID_125 = "125"


# DP 115
class MaintenanceResetItem(StrEnum):
    SIDE_BRUSH = "SideBsh"
    MAIN_BRUSH = "MainBsh"
    FILTER = "Filter"
    SENSOR = "Sensor"


# DP 5
class CleaningMode(StrEnum):
    AUTO = "auto"
    PAUSE = "Pause"
    CONTINUE = "Continue"
    NO_SWEEP = "Nosweep"
    SPOT_CLEAN = "Spot"
    SMALL_ROOL = "SmallRoom"


@dataclass
class MaintenanceItem:
    name: str
    icon: str
    status_dp: RobovacDPs
    reset_dp_value: MaintenanceResetItem


MAINTENANCE_ITEMS: list[MaintenanceItem] = [
    MaintenanceItem(
        name="Side brush",
        icon="mdi:broom",
        status_dp=RobovacDPs.ROBOVAC_SIDE_BSHTM_DPS_ID_112,
        reset_dp_value=MaintenanceResetItem.SIDE_BRUSH,
    ),
    MaintenanceItem(
        name="Main brush",
        icon="mdi:broom",
        status_dp=RobovacDPs.ROBOVAC_MAIN_BSHTM_DPS_ID_113,
        reset_dp_value=MaintenanceResetItem.MAIN_BRUSH,
    ),
    MaintenanceItem(
        name="Filter",
        icon="mdi:air-filter",
        status_dp=RobovacDPs.ROBOVAC_FILETR_TM_DPS_ID_114,
        reset_dp_value=MaintenanceResetItem.FILTER,
    ),
    MaintenanceItem(
        name="Sensor",
        icon="mdi:leak",
        status_dp=RobovacDPs.ROBOVAC_SENSOR_TM_DPS_ID_127,
        reset_dp_value=MaintenanceResetItem.SENSOR,
    ),
]


class FanSpeed(StrEnum):
    MOP = "Mop"
    QUIET = "Quiet"
    STANDARD = "Standard"
    TURBO = "Turbo"
    MAXIMUM = "Max"
    BOOST_IQ = "Boost_IQ"
