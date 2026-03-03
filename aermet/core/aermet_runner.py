"""
AERMET control file generation and execution.

Generates control files for all 3 AERMET stages:
  Stage 1: Extract & QA (surface + upper air data)
  Stage 2: Merge
  Stage 3: METPREP (boundary layer parameters → .SFC + .PFL output)

Executes AERMET.exe via subprocess and parses message files.
"""

import os
import subprocess

_BIN_DIR = os.path.join(os.path.dirname(__file__), '..', 'bin')


def _aermet_exe():
    """Locate AERMET executable."""
    exe = os.path.join(_BIN_DIR, 'aermet.exe')
    if os.path.exists(exe):
        return exe
    # Try without .exe for non-Windows
    exe2 = os.path.join(_BIN_DIR, 'aermet')
    if os.path.exists(exe2):
        return exe2
    return None


# ---------------------------------------------------------------------------
# Control file generation
# ---------------------------------------------------------------------------

def generate_stage1(work_dir, year, surface_file, upper_air_file,
                    sf_station_id, sf_lat, sf_lon,
                    ua_station_id, ua_lat, ua_lon,
                    start_month=1, end_month=12,
                    onemin_file=None):
    """
    Generate AERMET Stage 1 control file (EXTRACT + QA).

    Returns path to control file.
    """
    prefix = f's1_{year}'
    ctrl_path = os.path.join(work_dir, f'{prefix}.inp')

    start_date = f'{year}/01/01'
    if start_month != 1:
        start_date = f'{year}/{start_month:02d}/01'
    end_date = f'{year}/12/31'
    if end_month != 12:
        # Last day of month
        import calendar
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = f'{year}/{end_month:02d}/{last_day}'

    # Build SURFACE keywords
    oneminute_line = ''
    if onemin_file:
        oneminute_line = f'   ONEMINUTE   {onemin_file}'

    ctrl = f"""JOB
   MESSAGES   {prefix}.msg
   REPORT     {prefix}.rpt

UPPERAIR
   DATA       {upper_air_file}  IGRA
   EXTRACT    {prefix}_ua.ext
   AUDIT      UATT UAWS UALR
   QAOUT      {prefix}_ua.qa
   XDATES     {start_date}  TO  {end_date}
   LOCATION   {ua_station_id}  {ua_lat:.4f}  {ua_lon:.4f}

SURFACE
   DATA       {surface_file}  ISHD
   EXTRACT    {prefix}_sf.ext
   AUDIT      SLVP PRES CLHT TSKC PWTH APTS
   QAOUT      {prefix}_sf.qa
   XDATES     {start_date}  TO  {end_date}
   LOCATION   {sf_station_id}  {sf_lat:.4f}  {sf_lon:.4f}
{oneminute_line}
"""

    with open(ctrl_path, 'w') as f:
        f.write(ctrl)
    return ctrl_path


def generate_stage2(work_dir, year, onemin_file=None):
    """Generate AERMET Stage 2 control file (MERGE)."""
    prefix = f's2_{year}'
    s1_prefix = f's1_{year}'
    ctrl_path = os.path.join(work_dir, f'{prefix}.inp')

    oneminute_line = ''
    if onemin_file:
        oneminute_line = f'   ONEMINUTE   {onemin_file}'

    ctrl = f"""JOB
   MESSAGES   {prefix}.msg
   REPORT     {prefix}.rpt

UPPERAIR
   QAOUT      {s1_prefix}_ua.qa

SURFACE
   QAOUT      {s1_prefix}_sf.qa
{oneminute_line}

MERGE
   OUTPUT     {prefix}_merge.out
   XDATES     {year}/01/01  TO  {year}/12/31
"""

    with open(ctrl_path, 'w') as f:
        f.write(ctrl)
    return ctrl_path


def generate_stage3(work_dir, year, sf_station_id, sf_lat, sf_lon,
                    ua_station_id, ua_lat, ua_lon,
                    aersurface_file=None, anemometer_height=10.0,
                    manual_surface_chars=None):
    """
    Generate AERMET Stage 3 control file (METPREP).

    Args:
        aersurface_file: Path to AERSURFACE output file (US sites)
        manual_surface_chars: Dict with albedo, bowen, roughness for non-US sites
    """
    prefix = f's3_{year}'
    s2_prefix = f's2_{year}'
    ctrl_path = os.path.join(work_dir, f'{prefix}.inp')

    sfc_out = os.path.join('output', f'{year}.SFC')
    pfl_out = os.path.join('output', f'{year}.PFL')

    # Surface characteristics section
    surf_chars = ''
    if aersurface_file:
        surf_chars = f'   AERSURF    {aersurface_file}'
    elif manual_surface_chars:
        # Manual entry: single sector, all seasons
        albedo = manual_surface_chars.get('albedo', 0.18)
        bowen = manual_surface_chars.get('bowen', 1.0)
        roughness = manual_surface_chars.get('roughness', 0.15)
        surf_chars = f"""   FREQ_SECT  ANNUAL  1
   SECTOR     1   0  360
   SITE_CHAR  1  1  {albedo}  {bowen}  {roughness}
   SITE_CHAR  1  2  {albedo}  {bowen}  {roughness}
   SITE_CHAR  1  3  {albedo}  {bowen}  {roughness}
   SITE_CHAR  1  4  {albedo}  {bowen}  {roughness}"""
    else:
        # Defaults
        surf_chars = """   FREQ_SECT  ANNUAL  1
   SECTOR     1   0  360
   SITE_CHAR  1  1  0.18  1.0  0.15
   SITE_CHAR  1  2  0.18  1.0  0.15
   SITE_CHAR  1  3  0.18  1.0  0.15
   SITE_CHAR  1  4  0.18  1.0  0.15"""

    ctrl = f"""JOB
   MESSAGES   {prefix}.msg
   REPORT     {prefix}.rpt

METPREP
   DATA       {s2_prefix}_merge.out
   XDATES     {year}/01/01  TO  {year}/12/31
   OUTPUT     {sfc_out}
   PROFILE    {pfl_out}
   SURFDATA   {sf_station_id}  {year}
   UAIRDATA   {ua_station_id}  {year}
   SURFLOCN   {sf_lat:.4f}  {sf_lon:.4f}
   UAIRLOCN   {ua_lat:.4f}  {ua_lon:.4f}
   NWS_HGT    {anemometer_height}
   METHOD     REFLEVEL  SUBNWS
{surf_chars}
"""

    with open(ctrl_path, 'w') as f:
        f.write(ctrl)
    return ctrl_path


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_aermet(ctrl_path, work_dir, progress_cb=None):
    """
    Execute AERMET with a given control file.

    Returns dict with success, return_code, messages, warnings, errors.
    """
    exe = _aermet_exe()
    if not exe:
        return {
            'success': False,
            'return_code': -1,
            'error': 'AERMET executable not found. Place aermet.exe in aermet/bin/',
            'messages': [],
            'warnings': [],
            'errors': ['AERMET executable not found'],
        }

    ctrl_filename = os.path.basename(ctrl_path)

    if progress_cb:
        progress_cb('running', f'Running AERMET with {ctrl_filename}...')

    try:
        result = subprocess.run(
            [exe],
            input=ctrl_filename + '\n',
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=600,
        )

        # Parse the message file
        msg_file = ctrl_filename.replace('.inp', '.msg')
        msg_path = os.path.join(work_dir, msg_file)
        messages, warnings, errors = _parse_message_file(msg_path)

        success = result.returncode == 0 and len(errors) == 0

        if progress_cb:
            status = 'done' if success else 'error'
            progress_cb(status, f'AERMET {ctrl_filename}: {"OK" if success else "errors found"}')

        return {
            'success': success,
            'return_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'messages': messages,
            'warnings': warnings,
            'errors': errors,
        }
    except FileNotFoundError:
        return {
            'success': False,
            'return_code': -1,
            'error': 'AERMET executable not found or not runnable',
            'messages': [],
            'warnings': [],
            'errors': ['AERMET executable not found'],
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'return_code': -1,
            'error': 'AERMET timed out after 10 minutes',
            'messages': [],
            'warnings': [],
            'errors': ['AERMET execution timed out'],
        }


def run_aermet_all_stages(work_dir, year, surface_file, upper_air_file,
                           sf_station_id, sf_lat, sf_lon,
                           ua_station_id, ua_lat, ua_lon,
                           aersurface_file=None, onemin_file=None,
                           anemometer_height=10.0,
                           manual_surface_chars=None,
                           progress_cb=None):
    """
    Run all 3 AERMET stages for a single year.
    Returns dict with results from each stage and output file paths.
    """
    results = {}

    # Stage 1
    if progress_cb:
        progress_cb('stage1', f'AERMET Stage 1 ({year}): Extract & QA...')
    ctrl1 = generate_stage1(
        work_dir, year, surface_file, upper_air_file,
        sf_station_id, sf_lat, sf_lon,
        ua_station_id, ua_lat, ua_lon,
        onemin_file=onemin_file,
    )
    results['stage1'] = run_aermet(ctrl1, work_dir, progress_cb)
    if not results['stage1']['success']:
        return {'success': False, 'stage': 1, 'results': results}

    # Stage 2
    if progress_cb:
        progress_cb('stage2', f'AERMET Stage 2 ({year}): Merge...')
    ctrl2 = generate_stage2(work_dir, year, onemin_file=onemin_file)
    results['stage2'] = run_aermet(ctrl2, work_dir, progress_cb)
    if not results['stage2']['success']:
        return {'success': False, 'stage': 2, 'results': results}

    # Stage 3
    if progress_cb:
        progress_cb('stage3', f'AERMET Stage 3 ({year}): METPREP...')
    ctrl3 = generate_stage3(
        work_dir, year, sf_station_id, sf_lat, sf_lon,
        ua_station_id, ua_lat, ua_lon,
        aersurface_file=aersurface_file,
        anemometer_height=anemometer_height,
        manual_surface_chars=manual_surface_chars,
    )
    results['stage3'] = run_aermet(ctrl3, work_dir, progress_cb)

    sfc_path = os.path.join(work_dir, 'output', f'{year}.SFC')
    pfl_path = os.path.join(work_dir, 'output', f'{year}.PFL')

    return {
        'success': results['stage3']['success'],
        'results': results,
        'sfc_path': sfc_path,
        'pfl_path': pfl_path,
    }


# ---------------------------------------------------------------------------
# Message file parsing
# ---------------------------------------------------------------------------

def _parse_message_file(msg_path):
    """Parse an AERMET message file for messages, warnings, and errors."""
    messages = []
    warnings = []
    errors = []

    if not os.path.exists(msg_path):
        return messages, warnings, errors

    with open(msg_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if '***' in line and 'ERROR' in line.upper():
                errors.append(line)
            elif '***' in line and 'WARNING' in line.upper():
                warnings.append(line)
            elif line.startswith('***'):
                messages.append(line)
            # Also catch "W" and "E" prefixed messages
            elif line.startswith('E ') or line.startswith('E\t'):
                errors.append(line)
            elif line.startswith('W ') or line.startswith('W\t'):
                warnings.append(line)

    return messages, warnings, errors


def combine_sfc_files(sfc_files, output_path):
    """Combine multiple per-year .SFC files into one."""
    with open(output_path, 'w') as out:
        for i, path in enumerate(sorted(sfc_files)):
            with open(path, 'r') as f:
                for line in f:
                    out.write(line)
    return output_path


def combine_pfl_files(pfl_files, output_path):
    """Combine multiple per-year .PFL files into one."""
    with open(output_path, 'w') as out:
        for path in sorted(pfl_files):
            with open(path, 'r') as f:
                for line in f:
                    out.write(line)
    return output_path
