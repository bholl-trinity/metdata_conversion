"""
Project state management — tracks the configuration and progress
of an AERMET automation run.
"""

import json
import os
import time
import uuid

_PROJECTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'projects')


def create_project(location, data_period, completeness, is_us=True):
    """
    Create a new project workspace.

    Args:
        location: dict with lat, lon, display_name
        data_period: dict with num_years, start_year
        completeness: dict with threshold, basis ('quarterly' or 'annual')
        is_us: whether the site is in the US

    Returns project dict with id and paths.
    """
    project_id = str(uuid.uuid4())[:8]
    project_dir = os.path.join(_PROJECTS_DIR, project_id)
    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'surface'), exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'upper_air'), exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'one_minute'), exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'aermet'), exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'output'), exist_ok=True)

    start_year = data_period['start_year']
    num_years = data_period['num_years']

    project = {
        'id': project_id,
        'dir': project_dir,
        'created': time.time(),
        'location': location,
        'data_period': {
            'start_year': start_year,
            'end_year': start_year + num_years - 1,
            'num_years': num_years,
        },
        'completeness': completeness,
        'is_us': is_us,
        'surface_station': None,
        'upper_air_station': None,
        'status': 'created',
        'steps_completed': [],
        'errors': [],
        'results': {},
    }

    _save_project(project)
    return project


def load_project(project_id):
    """Load project state from disk."""
    path = os.path.join(_PROJECTS_DIR, project_id, 'project.json')
    if not os.path.exists(path):
        raise ValueError(f'Project {project_id} not found')
    with open(path, 'r') as f:
        return json.load(f)


def update_project(project, **kwargs):
    """Update project fields and save."""
    project.update(kwargs)
    _save_project(project)
    return project


def _save_project(project):
    """Persist project state to JSON."""
    path = os.path.join(project['dir'], 'project.json')
    with open(path, 'w') as f:
        json.dump(project, f, indent=2)
