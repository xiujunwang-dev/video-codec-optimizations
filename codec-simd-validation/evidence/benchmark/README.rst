Full-profile benchmark records
==============================

``benchmark-runs-20261118.zip`` contains the following original run paths:

* ``output/baseline-full-20261118/``: Git-source run, with 549 retained files.
* ``output/release-portable-full-20261118/``: installed-wheel portable run,
  with 207 retained files.
* ``output/release-reproduction-audit-20261118.json``: source and observation
  comparison.

The 758 files from the two runs and the comparison JSON were checked byte for
byte against the records used to prepare the manuscript. Each run also
contains its own inventory and SHA-256 checks. The portable run retains the
archive-source evidence and case execution records needed to inspect its
inputs and observations. To extract the paths exactly as referenced in
``evidence-audit.rst``, run from the software directory::

    unzip evidence/benchmark/benchmark-runs-20261118.zip -d .

The comparison found 229 matching observation records and 57 matching source
references. The complete run records and result meanings are described in
``evidence-audit.rst``. These are known historical cases. Both executions
used one host and followed tool-integration changes; their agreement is not
independent replication using identical software sources.

The run manifests retain original command paths and host details as recorded.
They are experimental records, not portable instructions or credential
stores. This supplement does not assert that a local path identifies a
published upstream checkout; the retained source and Git object identifiers
are provided for independent inspection.
