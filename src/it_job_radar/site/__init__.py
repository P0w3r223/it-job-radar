"""The published page: data gathering, chart rendering, and the template around them.

Split the way the collector is split — ``build.py`` decides *what* the page says,
``charts.py`` is pure rendering, and the template holds the words. Nothing here queries
the database directly: the page reads the same named queries as everything else, so it
cannot quietly diverge from the numbers the pipeline reports.
"""
