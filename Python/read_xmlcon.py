from pprint import pprint
from pathlib import Path
from termcolor import colored
import warnings
from lxml import etree

from seabirdscientific.cal_coefficients import (
    ConductivityCoefficients,
    Oxygen43Coefficients,
    PressureDigiquartzCoefficients,
    TemperatureCoefficients,
    TemperatureFrequencyCoefficients,
    ECOCoefficients,
    AltimeterCoefficients,
    PARCoefficients,
    SPARCoefficients,
)


def strip_ns(tag):
    """Return local tag name, but safely handle non-string tags (e.g., comments)."""
    if not isinstance(tag, str):
        return None
    return tag.split('}', 1)[-1] if '}' in tag else tag

def parse_xmlcon_sbe(xml_path: Path, prefer_equation: int = 1, keep_all_equations: bool = False):
    """
    Parse a Sea-Bird .xmlcon and return a list of sensor dicts with coefficients.
    - prefer_equation: choose which <... equation="..."> block to prioritize (default=1)
    - keep_all_equations: if True, keep all equations with eq0_/eq1_ prefixes
    """
    tree = etree.parse(str(xml_path))
    root = tree.getroot()

    sensors_out = list()

    # Iterate each <Sensor>, whose first element child is e.g., <TemperatureSensor>, <ConductivitySensor>, etc.
    for sensor_container in root.findall(".//SensorArray/Sensor"):
        # Keep only element children (skip comments, processing instructions, text nodes)
        sensor_nodes = [c for c in sensor_container if isinstance(getattr(c, "tag", None), str)]
        if not sensor_nodes:
            continue
        s = sensor_nodes[0]
        # print(s)

        # Skip any sensor nodes that were not actually used
        if s == "NotInUse":
            continue

        sensor_type = strip_ns(s.tag) or ""
        serial = (s.findtext("SerialNumber") or "").strip()
        calib_date = (s.findtext("CalibrationDate") or "").strip()
        useg_j = (s.findtext("UseG_J") or "").strip()

        coefs = {}
        meta_exclude = {
            "SerialNumber", "CalibrationDate", "UseG_J", "ConductivityType", "OutputType", "Free"
        }

        # Direct children that are coefficients on the sensor node itself
        for child in s:
            if not isinstance(getattr(child, "tag", None), str):  # skip comments / non-elements
                continue
            tag = strip_ns(child.tag)
            if not tag or tag in meta_exclude or tag in ("Coefficients", "CalibrationCoefficients"):
                continue
            txt = (child.text or "").strip()
            if not txt:
                continue
            try:
                coefs[tag] = float(txt.replace(" ", ""))  # tolerate stray spaces
            except ValueError:
                coefs[tag] = txt

        # Handle nested coefficient blocks (<Coefficients> / <CalibrationCoefficients>)
        blocks = [b for b in (s.findall("./Coefficients") + s.findall("./CalibrationCoefficients"))
                  if isinstance(getattr(b, "tag", None), str)]

        if blocks:
            eq_map = {}  # <<< FIX: initialize before filling
            for b in blocks:
                eq_attr = b.get("equation")
                eq_key = f"eq{eq_attr}" if eq_attr is not None else "eq"
                eq_dict = {}
                for c in b:
                    if not isinstance(getattr(c, "tag", None), str):  # skip comments
                        continue
                    k = strip_ns(c.tag)
                    if not k:
                        continue
                    t = (c.text or "").strip()
                    if not t:
                        continue
                    try:
                        eq_dict[k] = float(t.replace(" ", ""))
                    except ValueError:
                        eq_dict[k] = t
                eq_map[eq_key] = eq_dict

            if keep_all_equations:
                for eqk, d in eq_map.items():
                    for k, v in d.items():
                        coefs[f"{eqk}_{k}"] = v
            else:
                chosen = f"eq{prefer_equation}"
                chosen_dict = eq_map.get(chosen) or next(iter(eq_map.values()))
                coefs.update(chosen_dict)

        sensors_out.append({
            "sensor_type": sensor_type,
            "serial_number": serial,
            "calibration_date": calib_date,
            "useg_j": useg_j,
            "coefficients": coefs
        })

    return sensors_out

def populate_sensor_objects(sensor_list) -> dict:
    sensor_objects = dict()
    sensor_prefix = ''
    for c, s in enumerate(sensor_list):
        st = s['sensor_type']
        sn = str(s['serial_number'])
        coeffs = s["coefficients"]
        match st:
            case 'TemperatureSensor':
                sensor_prefix = 'temperature'
                if s.get('useg_j', 0) == 0:
                    obj = TemperatureCoefficients(
                        a0=coeffs["A"], a1=coeffs["B"], a2=coeffs["C"], a3=coeffs["D"]
                    )
                else:
                    obj = TemperatureFrequencyCoefficients(
                        g=coeffs["G"], h=coeffs["H"], i=coeffs["I"], j=coeffs["J"], f0=coeffs["F0"]
                    )

            case 'ConductivitySensor':
                sensor_prefix = 'conductivity'
                if s.get('useg_j', 0) == 0:
                    warnings.warn(
                        f"Conductivity sensor with serial number ({sn}) is old and is not currently supported"
                    )
                    continue
                obj = ConductivityCoefficients(
                    g=coeffs["G"], h=coeffs["H"], i=coeffs["I"], j=coeffs["J"],
                    cpcor=coeffs["CPcor"], ctcor=coeffs["CTcor"], wbotc=coeffs["WBOTC"]
                )

            case 'PressureSensor':
                sensor_prefix = 'pressure'
                obj = PressureDigiquartzCoefficients(
                    c1=coeffs["C1"], c2=coeffs["C2"], c3=coeffs["C3"],
                    d1=coeffs["D1"], d2=coeffs["D2"],
                    t1=coeffs["T1"], t2=coeffs["T2"], t3=coeffs["T3"], t4=coeffs["T4"], t5=coeffs["T5"],
                    AD590B=coeffs["AD590B"], AD590M=coeffs["AD590M"]
                )

            case 'AltimeterSensor':
                sensor_prefix = 'altimeter'
                obj = AltimeterCoefficients(
                    slope=coeffs["ScaleFactor"], offset=coeffs["Offset"]
                )

            case 'PARLog_SatlanticSensor':
                sensor_prefix = 'parlog'
                obj = PARCoefficients(
                    a0=coeffs["a0"], a1=coeffs["a1"], im=coeffs["Im"], multiplier=coeffs["Multiplier"]
                )

            case 'OxygenSensor':
                sensor_prefix = 'oxygen'
                obj = Oxygen43Coefficients(
                    soc=coeffs["Soc"], v_offset=coeffs["offset"], tau_20=coeffs["Tau20"],
                    a=coeffs["A"], b=coeffs["B"], c=coeffs["C"], e=coeffs["E"],
                    d0=coeffs["D0"], d1=coeffs["D1"], d2=coeffs["D2"],
                    h1=coeffs["H1"], h2=coeffs["H2"], h3=coeffs["H3"]
                )

            case 'Fluorometer':
                sensor_prefix = 'cdom'
                obj = ECOCoefficients(
                    slope=coeffs["Range"], offset=coeffs["Offset"]
                )

            case 'FluoroSeapointSensor':
                sensor_prefix = 'chlorophyll_a'
                obj = ECOCoefficients(
                    slope=coeffs["GainSetting"], offset=coeffs["Offset"]
                )

            case 'SPAR_Sensor':
                sensor_prefix = 'spar'
                obj = SPARCoefficients(
                    conversion_factor=coeffs["ConversionFactor"], a0=0, a1=0, im=0
                )

            case 'TurbidityMeter':
                sensor_prefix = 'turbidity'
                obj = ECOCoefficients(
                    slope=coeffs["ScaleFactor"], offset=coeffs["DarkVoltage"]
                )

            case 'NotInUse':
                print(f"Sensor channel {c} was not used")
                continue

            case 'None':
                warnings.warn(f"Unknown sensor type: {st!r} (SN: {sn})")
                continue

        name = f"{sensor_prefix}_coefs_sn{sn}"
        sensor_objects[name] = obj

    func_string = colored("read_xmlcon", "green")
    print(func_string + colored(" executed successfully!", "yellow"))

    return sensor_objects


def read_xmlcon(xmlcon_path: str) -> list:
    sensor_list = parse_xmlcon_sbe(xmlcon_path, prefer_equation=1, keep_all_equations=False)
    sensor_object_dict = populate_sensor_objects(sensor_list)
    return sensor_object_dict


def main(xmlcon_path: str) -> None:
    sensors = read_xmlcon(xmlcon_path)
    pprint(sensors, sort_dicts=False, width=60)


if __name__ == "__main__":

    mypath = Path.cwd()
    # path_to_xmlcon_file = mypath / "data/SBE911plus/LAT2025146_Deep_Corrected.xmlcon"
    path_to_xmlcon_file = mypath / "data/SBE911plus/CAR2023573_Events_061_to_132_Corrected.xmlcon"
    main(xmlcon_path=path_to_xmlcon_file)
