"""AD-1186 (#1123) Ship Trials: the versioned trial catalog and its predeclared policy.

Tests and fixtures only, beside AD-1143's ``tests/ablation`` harness: the catalog is hashed over
the bytes ``sigma_goals.sha256_file`` hashes, and its policy's ``iterations``, ``alpha`` and
``seed`` are the parameters ``sigma_stats.bootstrap_ci`` takes. ``src/probos`` does not import
this package.
"""
