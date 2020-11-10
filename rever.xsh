$PROJECT = $GITHUB_REPO = 'conda-docker'
$GITHUB_ORG = 'conda-incubator'
$PYPI_SIGN = False
$ACTIVITIES = [
    'authors',
    'version_bump',
    'changelog',
    'tag',
    'push_tag',
    'pypi',
    #'conda_forge',
    'ghrelease'
]
$AUTHORS_FILENAME = 'AUTHORS.md'
$VERSION_BUMP_PATTERNS = [
    ('conda_docker/__init__.py', r'__version__\s*=.*', '__version__ = "$VERSION"'),
    ('setup.py', r'version\s*=.*,', 'version="$VERSION",'),
]
$CHANGELOG_FILENAME = 'CHANGELOG.md'
$CHANGELOG_TEMPLATE = 'TEMPLATE.md'
$CHANGELOG_PATTERN = "<!-- current developments -->"
$CHANGELOG_HEADER = """
<!-- current developments -->

## v$VERSION
"""
