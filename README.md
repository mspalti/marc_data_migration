# Record Modification Tool

Python modules created for migration of Pacific Northwest College of Art (PNCA) records to 
Alma (Orbis-Cascade Alliance SLIS). Uses [pymarc](https://gitlab.com/pymarc/pymarc).

The features are:

* Plugins that define rules for record transformations.
* A module for updating records with data from the OCLC Worldcat API.
* Functions for generating reports.

```
usage: processor.py [-h] [-p module name] [-m] [-r] [-pm] [-db database name]
                    [-di] [-nt] [-dft] [-t] [-tm] [-so] [-oc] [-ccf] [-d]
                    [-dupt] [-dupm] [-comp]
                    source

Process marc records.

positional arguments:
  source                Required: the path to the marc file to be processed

optional arguments:
  -h, --help            show this help message and exit
  -p module name, --plugin module name
                        The plugin module used for record modifications.
                        Example: processors.plugins.pnca.pnca_policy
  -m, --modify-recs     Just modify records using the provided plugin.
  -r, --replace-fields  Replace fields with fields from the OCLC record.
  -pm, --perfect-match  Perfect OCLC title match will be required; records
                        with lower fuzzy match ratios are written to a
                        separate file.
  -db database name, --use-database database name
                        Provide name of the postgres database name to use
                        instead of the OCLC API. This significantly speeds up
                        processing.
  -di, --database-insert
                        Insert records into database while replacing fields
                        with OCLC API data. Requires --use-database flag with
                        database name.
  -nt, --no-title-check
                        Skip the fuzzy title match on 245 fields before
                        updating records. You probably do not want to do this.
  -dft, --do-fuzzy-test
                        This option adds an additional test of fuzzy match
                        records when the OCLC number was found based only on
                        the 003 label.
  -t, --track-fields    Create an audit log of modified fields.
  -tm, --track-title-matches
                        Create audit log of fuzzy title matches.
  -so, --save-oclc      Save records from OCLC to local xml file during while
                        running the replacement task.
  -oc, --oclc-records   Only download marcxml from OCLC, no other tasks
                        performed.
  -ccf, --check-control-field-db
                        Reports duplicate 001/003 combinations.
  -d, --duplicates      Checks for duplicate OCLC numbers in the database.
  -dupt, --check-duplicate-title
                        Check for duplicate 245 fields.
  -dupm, --check-duplicate-main
                        Check for duplicate main entry fields.
  -comp, --compare_oclc_numbers
                        Retrieve OCLC records and compare oclc numbers in the
                        response and with the original input file. Logs the
                        discrepancies for analysis.
                        
Example:

process.py --replace-fields --perfect-match --plug-in processors.plugins.lib.lib_policy --track-fields 
--track-title-matches --do-fuzzy-test --db database_name /home/user/marcfile 
```

## Plugins

You can define rules for modifying records using an `UpdatePolicy` plugin and providing it at runtime using
the `--plug-in` argument. This package includes the plugin we developed for our migration into Alma and a 
sample starter plugin.

## Reports
You can run a number of reports that we developed to help with analyzing errors found in records and reviewing
the output of OCLC field substitution. The analysis of OCLC substitutions include metrics to help with
determining the accuracy of record matches based on the OCLC number found in the input record.

## OCLC API Record Harvesting
You can harvest OCLC records to speed up subsequent processing in two ways. The method used in package is adding
records to a postgres database using the `--database-insert` option and then applying the database to subsequent 
processing. You can use the database when processing by adding the `-db` flag, and the database name. 

If you like, you can also write OCLC records to a MARCXML file.

## Updating with OCLC Data
If your records require this step, you can update and/or add new OCLC record fields. For large projects, this 
will require and OCLC API developer key (path to key defined in `proccessor.py`). Use 
the `--replace-fields` argument and additional arguments such as `--perfect-match`, `--track-title-matches`, and
`--db`.

If you replace fields you will probably want to review and update the `substitution_array` defined in 
`replace_configuration.py`. This list determines which fields get updated with OCLC data. There are two
replacement strategies available: `replace_and_add` and `replace_only`.  The obvious difference is that
`replace_and_add` (default) will add new fields to the record when provided in the OCLC response.

The record locations used for the OCLC number are:

* 035 with OCoLC label
* 001 value with an OCLC prefix
* 001/003 combination with an OCoLC label, and an 001 value that does not have an OCLC prefix

When using the `--perfect-match` argument, only records with perfect matches on OCLC 245(a)(b)
get written to the `updated-records` file. For imperfect matches, the program updates the record with OCLC
data, but writes the output to a `fuzzy-updated-records` file for later review. A `fuzzy-match-passed` 
or `fuzzy-match-failed` label gets added to the 962 field so these records can be found for review
after records are loaded into the system. To assist with the later review, you can
add the `--track-title-matches` argument.  This generates a tab-delimited audit file with accuracy metrics
based on Levenshtein Distance and Jaccard Similarity. Sorting on these metrics can be useful.

The `--do-fuzzy-test` argument is a special case that might be helpful elsewhere.  
In our data set, OCLC numbers for 001 values without an OCLC prefix ('ocn', 'ocm', or 'on') 
were highly inaccurate. The `--do-fuzzy-test` argument triggers a secondary evaluate that excludes 
records that do not meet an accuracy (Levenshtein Distance) threshold. Records that do not meet the 
threshold get written to the `non-modified` records file without an OCLC update. The program replaces 
the OCLC 001/003 values in the record with a unique local identifier provided by the plugin `set_local_id()` 
method. This sort of fine-tuning is obviously dependent the results you see in your own data.

When you provid the `--perfect-match` argument, records with a perfect match on the OCLC 245(a)(b) subfields
get written to the `updated-records` file. Imperfect matches get written to a `fuzzy-updated-records` file.

Records that do not have an OCLC match (or are rejected by `--do-fuzzy-test` mentioned above) get written 
to a `non-updated-records` file.

# Output Files

## updated-records
Records that are updated with OCLC data.

## updated-online
Records for online resources that are updated with OCLC data.

## non-updated-records
Original input records that are not updated with OCLC data.

## non-updated-online
Original input records for online resources that are not updated with OCLC data.

## bad-records
Records that could not be processed by pymarc because of errors in the original marc record.

## fuzzy-updated-records
Records that have been updated with OCLC data but lack an exact match on the 245 fields. 

## fuzzy-online-records
Records for electronic resources that have been updated with OCLC data but lack an exact match on the 245 fields. 

## fuzzy-original-records
The original input records for comparison with fuzzy-updated-records.

# Audit files

## title-fuzzy-match
A tab-delimited text file with information on fuzzy match records: Levenshtein Distance, Jaccard Similarity,
original title, oclc title, pass/fail result, oclc number. 

## fields-audit
A tab-delimited file recording all field replacements: oclc number, tag, new value, original value.

## mat-type-analysis
Identifies conflict between call number and location (300) fields. Idiosyncratic, so uses a plugin method. 
Tab-delimited.

## field-035-details
Captures subfield "z", duplicate or missing "a"

## duplicate_title_fields
Reports all records with multiple 245 fields

## duplicate_100_fields
Reports all records with multiple 1xx fields

## missing-245a
Records that have no 245(a) value.

# Harvest

## oclc
OCLC MARCXML written to this file when `--save-oclc` or `--oclc-records` are used.
