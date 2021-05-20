import time
from urllib.error import HTTPError
import xml.etree.ElementTree as ET
from pymarc import MARCReader, Field, Leader, TextWriter

from modules.add_response_to_database import DatabaseUpdate
from modules.field_generators import ControlFieldGenerator, DataFieldGenerator
from modules.location_mapping import LocationMapper
from modules.oclc_connector import OclcConnector
from db_connector import DatabaseConnector
import modules.utils as utils
import modules.field_replacement_count as field_count
import datetime
import re


class RecordsModifier:
    connector = OclcConnector()
    database_update = DatabaseUpdate()

    ns = {'': 'http://www.loc.gov/MARC21/slim'}

    oclc_developer_key = ''

    failed_oclc_lookup_count = 0
    updated_001_count = 0
    updated_003_count = 0
    updated_leader_count = 0

    ebook_count = 0
    online_periodical_count = 0
    streaming_video_count = 0

    field_audit_writer = None

    def update_fields_using_oclc(self,
                                 file,
                                 database_name,
                                 password,
                                 require_perfect_match,
                                 substitutions,
                                 title_check,
                                 database_insert,
                                 writer,
                                 unmodified_writer,
                                 bad_writer,
                                 title_log_writer,
                                 oclc_xml_writer,
                                 field_audit_writer,
                                 fuzzy_record_writer,
                                 updated_online_writer,
                                 unmodified_online_writer,
                                 fuzzy_online_writer,
                                 cancelled_oclc_writer,
                                 oclc_developer_key):
        """
        Updates records from input marc file with data obtained
        from OCLC worldcat.  The method takes a substitutions array
        that specifies the fields to be updated.
        :param file: The marc file (binary)
        :param database_name: Optional database name
        :param password: Optional database password
        :param require_perfect_match: If True a perfect title match with OCLC is required
        :param substitutions: The array of fields to update
        :param title_check: If true will do 245a fuzzy title match
        :param database_insert: If true insert API repsonse into database
        :param writer: The output file writer
        :param unmodified_writer: The output file writer for unmodifed records
        :param bad_writer: The output file records that cannot be processed
        :param title_log_writer: The output title for fuzzy matched titles
        :param oclc_xml_writer: The output file for OCLC xml
        :param field_audit_writer: The output file tracking field updates
        :param fuzzy_record_writer: Output pretty records with fuzzy OCLC title match
        :param updated_online_writer: Output pretty records for updated online items
        :param unmodified_online_writer: Output pretty records for unmodified online items
        :param fuzzy_online_writer: Output pretty records for fuzzy online items
        :param fuzzy_record_writer: Output pretty records with fuzzy OCLC title match
        :param cancelled_oclc_writer: Outputs 035(z) audit
        :param oclc_developer_key: The developer key used to query OCLC
        :return:
        """

        self.field_audit_writer = field_audit_writer

        dt = datetime.datetime.now()

        missing_required_field_writer = TextWriter(
            open('output/audit/records-with-missing-field-pretty-' + str(dt) + '.txt', 'w'))

        if database_insert:
            bad_oclc_reponse_writer = open('output/xml/bad-oclc-response-' + str(dt) + '.xml', 'w')

        if require_perfect_match:
            original_fuzzy_writer = TextWriter(
                open('output/updated-records/fuzzy-original-records-pretty-' + str(dt) + '.txt', 'w'))

        self.oclc_developer_key = oclc_developer_key

        if oclc_xml_writer is not None:
            oclc_xml_writer.write('<?xml version="1.0" encoding="UTF-8" standalone="no" ?>')
            oclc_xml_writer.write('<collection xmlns="http://www.loc.gov/MARC21/slim" '
                                  'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                                  'xsi:schemaLocation="http://www.loc.gov/standards/marcxml/schema/MARC21slim.xsd">')

        conn = None
        cursor = None
        if database_name:
            # If database provided, initialize the connection and get cursor. If not
            # provided the OCLC API will be used.
            db_connect = DatabaseConnector()
            conn = db_connect.get_connection(database_name, password)
            print("Database opened successfully.")
            cursor = conn.cursor()

        with open(file, 'rb') as fh:
            modified_count = 0
            unmodified_count = 0
            bad_record_count = 0
            fuzzy_record_count = 0
            # Set to permissive to avoid exiting loop; report
            # unreadable records in the output. Prevent python utf-8
            # handling.
            reader = MARCReader(fh, permissive=True, utf8_handling='ignore')

            for record in reader:
                if record:
                    field_001 = None
                    field_035 = None
                    location = None
                    input_oclc_number = None
                    oclc_001_value = None
                    oclc_response = None
                    title = ''

                    # Records to online titles should have "o" in position
                    # 23 of the 008 field.  These records have been updated
                    # by PNCA, so writing them to separate file without
                    # modification.
                    is_online = self.__is_online(record)

                    try:
                        if not record.title():
                            print('Record missing 245(a)')
                            missing_required_field_writer.write(record)
                        if record['245'] and record['245']['a']:
                            title = utils.get_original_title(record)
                        if len(record.get_fields('001')) == 1:
                            field_001 = utils.get_oclc_001_value(record['001'], record['003'])
                        if len(record.get_fields('035')) > 0:
                            # Note: side effect of this method call is logging 035(z) subfields
                            # to the cancelled_oclc_writer file handle.
                            field_035 = self.__get_035_value(record, cancelled_oclc_writer)

                        location_mapper = LocationMapper()
                        location_field = self.__get_852b(record)

                        if location_field == '1st Floor CDs' or location_field == 'OVERSIZE PERIODICALS':
                            location = location_mapper.get_location(location_field)
                            self.__replace_location(record, location)
                        else:
                            call_number = self.__get_call_number(record)
                            if not call_number:
                                if field_001 is not None:
                                    print('Missing call number for: ' + field_001)
                                elif field_035 is not None:
                                    print('Missing call number for: ' + field_035)
                            else:
                                location = location_mapper.get_location_by_callnumber(call_number)
                                self.__add_location_to_record(record, location)

                    except Exception as err:
                        print('error reading fields from input record.')
                        print(err)

                    try:
                        # Use 001 by default.
                        if field_001:
                            input_oclc_number = field_001
                        elif field_035:
                            input_oclc_number = field_035

                        self.__add_local_field_note(record)

                        # If input record includes an OCLC number retrieve record from
                        # the API or local database.
                        if input_oclc_number:
                            oclc_response = self.__get_oclc_response(input_oclc_number, cursor, database_insert)

                        if oclc_response is not None:
                            oclc_001_value = self.__get_field_text('001', oclc_response)
                            # Log if the OCLC response does not include 001. This can happen
                            # if we get an error diagnostic from the API. That should
                            # quite rare since up to 3 requests are made. The error
                            # to expect is file not found.
                            if input_oclc_number and not oclc_001_value:
                                print('Missing oclc 001 for ' + input_oclc_number)
                                if bad_oclc_reponse_writer:
                                    bad_oclc_reponse_writer.write(ET.tostring(oclc_response,
                                                                              encoding='utf8',
                                                                              method='xml'))
                            # Add record to database if requested.
                            if input_oclc_number and database_insert:
                                self.__database_insert(cursor,
                                                       conn,
                                                       input_oclc_number,
                                                       oclc_001_value,
                                                       oclc_response, title)

                            # Write to the OCLC record to file if file handle was provided.
                            if oclc_xml_writer is not None:
                                oclc_xml_writer.write(str(ET.tostring(oclc_response,
                                                                    encoding='utf8',
                                                                    method='xml')))

                        # Modify records if input title matches that of the OCLC response.
                        #
                        # If "require_perfect_match" is True, validation checks for an exact match
                        # on the 245(a)(b) fields. Only exact matches are written to the
                        # updated records file.  Imperfect (fuzzy) matches are written to a
                        # separate file labeled in the 962 for review.
                        #
                        # If the "require_perfect_match" parameter is False, field substitution
                        # will take place when the similarity ratio is greater than the minimum value
                        # defined in the matcher class. Records will be written to the updated
                        # records output file.
                        #
                        # Verification will fail when the oclc_response is None. The record
                        # will be written to unmodified records file.

                        if utils.verify_oclc_response(oclc_response, title, None, record.title(),
                                                      input_oclc_number, title_check, require_perfect_match):

                            self.replace_fields(oclc_001_value, record, substitutions, oclc_response)
                            # Update count.
                            modified_count += 1
                            if is_online:
                                updated_online_writer.write(record)
                            else:
                                writer.write(record)

                        # When "require_perfect_match" is True make substitutions for records
                        # with an imperfect OCLC title match. These records will be written to a
                        # separate file. Records will be labeled using the 962 field.

                        elif oclc_response is not None and require_perfect_match:

                            field_generator = DataFieldGenerator()

                            # Write the original version of the record to a separate output
                            # file so the original is available to the reviewer.
                            original_fuzzy_writer.write(record)

                            # Next, replace fields with OCLC data.
                            self.replace_fields(oclc_001_value, record, substitutions, oclc_response)

                            # Now test the OCLC response with allowance for fuzzy matches on the title.
                            # The minimum match ratio is defined in the FuzzyMatcher class. Adjust the
                            # ratio to increase or decrease the number of records that "pass".
                            #
                            # The matcher uses token sorting to help reduce failures that result from
                            # trivial order differences in the 255(a)(b) subfields.
                            #
                            # When a record passes the verification step, add the corresponding 962 field
                            # label to the record.

                            if utils.verify_oclc_response(oclc_response, title, title_log_writer, record.title(),
                                                          input_oclc_number, title_check, False):
                                field = field_generator.create_data_field('962', [0, 0],
                                                                          'a', 'fuzzy-match-passed')
                                record.add_ordered_field(field)

                                if is_online:
                                    fuzzy_online_writer.write(record)
                                else:
                                    fuzzy_record_writer.write(record)

                            # For records that to not meet the title threshold, add the corresponding 962 field
                            # label to the record. Many records that "fail" will be valid OCLC responses. This
                            # label allows the reviewer to review records with the greatest title variance.

                            else:
                                field = field_generator.create_data_field('962', [0, 0],
                                                                          'a', 'fuzzy-match-failed')
                                record.add_ordered_field(field)
                                if is_online:
                                    fuzzy_online_writer.write(record)
                                else:
                                    fuzzy_record_writer.write(record)

                            # Update counts.
                            fuzzy_record_count += 1
                            modified_count += 1

                        # For records with no OCLC response, write to a separate file and continue.

                        else:
                            unmodified_count += 1
                            if is_online:
                                unmodified_online_writer.write(record)
                            else:
                                unmodified_writer.write(record)

                    except HTTPError as err:
                        print(err)
                    except UnicodeEncodeError as err:
                        print(err)

                else:
                    bad_record_count += 1
                    print(reader.current_exception)
                    print(reader.current_chunk)
                    bad_writer.write(reader.current_chunk)

        if oclc_xml_writer is not None:
            oclc_xml_writer.write('</collection>')

        if conn is not None:
            conn.close()

        print('Modified record count: ' + str(modified_count))
        print('Unmodified record count: ' + str(unmodified_count))
        print('Fuzzy record count: ' + str(fuzzy_record_count))
        print('Bad record count: ' + str(bad_record_count))
        print()

        field_count_dict = field_count.get_field_count()
        field_c = 0
        print('leader: ' + str(self.updated_leader_count))
        print('001: ' + str(self.updated_001_count))
        print('003: ' + str(self.updated_003_count))
        for key in field_count_dict.keys():
            print(key + ': ' + str(field_count_dict[key]))
            field_c += field_count_dict[key]

        print('Total fields replaced: ' + str(field_c))
        print()

        if database_insert:
            print('Failed OCLC record retrieval count: ' + str(self.failed_oclc_lookup_count))
        print()

        print('Ebook record count: ' + str(self.ebook_count))
        print('Online periodical record count: ' + str(self.online_periodical_count))
        print('Streaming video record count: ' + str(self.streaming_video_count))
        total_electronic_records = self.streaming_video_count + self.ebook_count + self.online_periodical_count
        print('Total electronic records: ' + str(total_electronic_records))

    def __get_oclc_response(self, oclc_number, cursor, database_insert):
        """
        Retrieves the OCLC record from API or database
        :param oclc_number: record number
        :param cursor: database cursor
        :param database_insert: database insert task boolean
        :return: oclc response node
        """
        oclc_response = None
        if cursor is not None and not database_insert:
            cursor.execute("""SELECT oclc FROM oclc where id=%s""", [oclc_number])
            row = cursor.fetchone()
            if row:
                oclc_response = ET.fromstring(row[0])
        else:
            # This will make multiple API requests if
            # initial response returns diagnostic xml.
            oclc_response = self.__get_oclc_api_response(oclc_number)

        return oclc_response

    def __get_field_text(self, field, oclc_response):
        """
        Gets value for the requested field text.
        :param field: field tag
        :param oclc_response: OCLC marcxml or root node
        :return: field value
        """
        oclc_field = self.__get_oclc_element_field(field, oclc_response)
        if oclc_field is not None:
            return oclc_field.text

        return None

    @staticmethod
    def __replace_location(record, location):
        if len(record.get_fields('852')) > 0:
            try:
                fields = record.get_fields('852')
                fields[0].delete_subfield('b')
                fields[0].add_subfield('b', location, 1)
                record.remove_fields('852')
                record.add_ordered_field(fields[0])
            except Exception as err:
                print('Error replacing location in record.')
                print(err)

    @staticmethod
    def __add_location_to_record(record, location):
        if len(record.get_fields('852')) > 0:
            try:
                fields = record.get_fields('852')
                fields[0].add_subfield('b', location, 1)
                record.remove_fields('852')
                record.add_ordered_field(fields[0])
            except Exception as err:
                print('Error adding location to record.')
                print(err)

    @staticmethod
    def __get_oclc_element_field(field, oclc_response):
        """
        Gets the field element from oclc response.
        :param field: the field to return
        :param oclc_response: the initial OCLC response (used if valid)
        :return: the OCLC field node
        """
        if oclc_response is not None:
            return oclc_response.find('./*[@tag="' + field + '"]')
        return None

    @staticmethod
    def __add_local_field_note(record):
        """
        Alma NZ will preserve local fields when they are
        labelled with subfield 9 equal to 'local'.
        :param record: pymarc record
        :return:
        """
        fields = ['590', '690', '852', '900', '918', '921', '994', '998', '936']
        for field in fields:
            for rec_field in record.get_fields(field):
                rec_field.add_subfield('9', 'local')

    def __is_online(self, record):
        """
        The hook for electronic records in our current
        input data is the 900 field.
        :param record: a pymarc record
        :return: True if record is electronic
        """
        field_900 = record.get_fields('900')
        # There can be multiple fields
        for field in field_900:
            subfield = field.get_subfields('a')
            # inspect subfield "a"
            if len(subfield) > 0:
                field_value = subfield[0]
                if field_value:
                    if field_value.find('STREAMING VIDEO') > -1:
                        self.streaming_video_count += 1
                        return True
                    if field_value.find('EBOOK') > -1:
                        self.ebook_count += 1
                        return True
                    if field_value.find('ONLINE PERIODICAL') > -1:
                        self.online_periodical_count += 1
                        return True
        return False

    @staticmethod
    def __remove_fields(field, record):
        """
        Removes field, first checking for 1xx an removing
        all 1xx fields on match.  The OCLC record may include
        a different 1xx than the original file, so this is
        necessary. This method is called after a successful
        OCLC data fetch and before OCLC data is added to the
        record.

        :param field: current field
        :param record: current record
        :return:
        """
        field_1xx_regex = re.compile('^1\d{2}')
        # Single 1xx field allowed in record.
        if field_1xx_regex.match(field):
            record.remove_fields('100', '110', '111', '130')
        else:
            record.remove_fields(field)

    @staticmethod
    def __get_original_values(originals):
        """
        Get values from field array.
        :param originals: fields from original marc record
        :return: list of field values
        """
        values = []
        for original in originals:
            values.append(original.value())
        return values

    def __write_to_audit_log(self, replacement_field, original_fields, field, control_field, writer):
        """
        Writes field replacements to audit log.
        :param replacement_field: replacement field tag
        :param original_fields: fields from original marc record
        :param field: current pymarc Field
        :param control_field: value of the record 001 or the record title varying with data and control field contexts.
        :param writer: the audit log writer
        :return:
        """
        for single_field in self.__get_original_values(original_fields):
            # Output order: oclc#, tag, new field value, original field value.
            writer.write(control_field + '\t'
                         + replacement_field + '\t'
                         + field.value() + '\t'
                         + single_field + '\n')

        field_count.update_field_count(replacement_field)

    @staticmethod
    def __move_field(record, current_field_tag, new_field_tag):
        """
        Moves field to a new field in the record. Used
        to preserve local fields during ingest.
        :param record: pymar record
        :param current_field_tag: tag of the current field
        :param new_field_tag: tag of the target field
        :return:
        """
        fields = record.get_fields(current_field_tag)
        for field in fields:
            sub_fields = field.subfields_as_dict()
            target_field = Field(
                tag=new_field_tag,
                indicators=[field.indicator1, field.indicator2],
                subfields=sub_fields
            )
            record.remove_field(field)
            record.add_ordered_field(target_field)
            field_count.update_field_count(new_field_tag)

    @staticmethod
    def __conditional_move_field(record, replacement_field_tag, target_field_tag, oclc_response):
        """
        Conditionally moves field to a new field in the record. Used
        to preserve 505 field during ingest when no replacement is
        provided by OCLC.
        :param record: pymarc record
        :param replacement_field_tag: tag of the field to move
        :param target_field_tag: tag of the new field
        :param oclc_response: the OCLC marcxml response
        :return:
        """
        # Test to see if replacement was provided in OCLC record.
        # If not, move field in the current record to preserve in data
        # in a localfield.
        oclc_field = oclc_response.find('./*[@tag="' + replacement_field_tag + '"]')
        if oclc_field is None:
            fields = record.get_fields(replacement_field_tag)
            for field in fields:
                sub_fields = field.subfields_as_dict()
                keys = sub_fields.keys()
                subs_new = []
                for key in keys:
                    subs_list = sub_fields[key]
                    for val in subs_list:
                        subs_new.append(key)
                        subs_new.append(val)

                target_field = Field(
                    tag=target_field_tag,
                    indicators=[field.indicator1, field.indicator2],
                    subfields=subs_new
                )
                record.remove_field(field)
                record.add_ordered_field(target_field)
                field_count.update_field_count(target_field_tag)

    def __data_field_update(self, record, replacement_field_tag, oclc_response):
        """
        Updates the record data field using OCLC XML response.

        :param record: the pymarc Record
        :param replacement_field_tag: the field to replace
        :param oclc_response: the OCLC XML response
        """
        field_generator = DataFieldGenerator()
        # get the replacement fields from OCLC response
        tags = oclc_response.findall('.//*[@tag="' + replacement_field_tag + '"]', self.ns)
        if len(tags) > 0:
            # get the replacement fields from the original record for adding to audit file.
            original_fields = record.get_fields(replacement_field_tag)
            field_001 = record['001'].value()
            # remove replacement fields from the original record
            self.__remove_fields(replacement_field_tag, record)
            for f in tags:
                field = field_generator.get_data_field(f, f.attrib, replacement_field_tag)
                if field:
                    if self.field_audit_writer:
                        self.__write_to_audit_log(replacement_field_tag, original_fields, field,
                                                  field_001, self.field_audit_writer)
                    # add new field with OCLC data to record
                    record.add_ordered_field(field)
        else:
            # this moves fields within the record.
            # TODO: move this to it's own method and add move field configuration to avoid hard-coding.
            if replacement_field_tag == '505':
                self.__conditional_move_field(record, replacement_field_tag, '590', oclc_response)
            if replacement_field_tag == '500':
                self.__conditional_move_field(record, replacement_field_tag, '591', oclc_response)

    def __control_field_update(self, record, replacement_field, oclc_response):
        """
        Updates the record control fields using OCLC XML response.

        :param record: the pymarc Record
        :param replacement_field: the field to replace
        :param oclc_response: the OCLC XML response
        """
        field_generator = ControlFieldGenerator()
        field = field_generator.get_control_field(replacement_field, oclc_response)
        if field:
            original_fields = record.get_fields(replacement_field)
            field_001 = record['001'].value()
            if self.field_audit_writer:
                self.__write_to_audit_log(replacement_field, original_fields, field,
                                          field_001, self.field_audit_writer)

            record.remove_fields(replacement_field)
            record.add_ordered_field(field)

    @staticmethod
    def __add_oclc_001_003(record, oclc_number):
        """
        Add 001 and 003 fields to a record. Use to guarantee this
        information is in every record.
        :param record:  pymarc record
        :param oclc_number: OCLC number
        """
        record.remove_fields('001')
        record.remove_fields('003')
        field_001 = Field(
            tag='001',
            data=oclc_number
        )
        field_003 = Field(
            tag='003',
            data='OCoLC'
        )
        record.add_ordered_field(field_001)
        record.add_ordered_field(field_003)

    def __replace_leader(self, record, oclc_reponse):
        """
        Replaces existing record leader with OCLC value
        :param record: The record pymarc root node
        :param oclc_reponse: the OCLC API response node
        :return:
        """
        oclc_leader = oclc_reponse.find('./', self.ns)
        new_leader = Leader(oclc_leader.text)
        if new_leader:
            record.leader = new_leader

    def __get_oclc_api_response(self, field_value):
        """
        Makes OCLC API request and tests for a valid response. Will attempt
        up to 3 requests before failing.
        :param field_value: the oclc number
        :return: oclc response node
        """

        oclc_response = self.connector.get_oclc_response(field_value, self.oclc_developer_key)
        oclc_field = oclc_response.find('./*[@tag="001"]')
        # API returns occasional error. Second attempt
        # should be enough to guarantee we get a response.
        if oclc_field is None:
            time.sleep(0.5)
            oclc_response = self.connector.get_oclc_response(field_value, self.oclc_developer_key)
            oclc_field = oclc_response.find('./*[@tag="001"]')
        if oclc_field is None:
            # extra special repeat performance
            time.sleep(0.3)
            oclc_response = self.connector.get_oclc_response(field_value, self.oclc_developer_key)
            oclc_field = oclc_response.find('./*[@tag="001"]')
        if oclc_field is None:
            self.failed_oclc_lookup_count += 1
            oclc_response = None

        return oclc_response

    @staticmethod
    def __get_035_value(record, cancelled_oclc_writer):
        """
        Returns value of OCLC 035 field. Side effects are logging
        subfield z's and printing a notice when a duplicate 035(a)
        is encountered.
        :param record: record node
        :return: 035 value
        """
        field_035 = None
        if len(record.get_fields('035')) > 0:
            fields = record.get_fields('035')
            for field in fields:
                subfields = field.get_subfields('a')
                if len(subfields) > 1:
                    print('duplicate 035a')
                elif len(subfields) == 1:
                    field_035 = utils.get_oclc_035_value(subfields[0])
                    utils.log_035z(record['035'], field_035, cancelled_oclc_writer)
        return field_035

    @staticmethod
    def __get_852b(record):
        location_field = None
        if len(record.get_fields('852')) > 0:
            fields = record.get_fields('852')
            for field in fields:
                subfields = field.get_subfields('b')
                if len(subfields) == 1:
                    location_field = subfields[0]
        return location_field

    @staticmethod
    def __get_call_number(record):
        """
        Returns value of OCLC 090 field.
        :param record: record node
        :return: call number
        """
        call_number = None
        if len(record.get_fields('852')) > 0:
            fields = record.get_fields('852')
            for field in fields:
                subfields = field.get_subfields('h')
                if len(subfields) == 1:
                    call_number = subfields[0]
        return call_number

    def __database_insert(self, cursor, conn, field, oclc_field, oclc_response, title):
        """
        Insert OCLC record into local database
        :param cursor: db cursor
        :param conn: database connection
        :param field:  the 001 field value from local input
        :param oclc_field: the 001 node from oclc response
        :param oclc_response: the OCLC xml reponse
        :param title: the item title
        :return:
        """
        if cursor is not None:
            try:
                self.database_update.add_response(
                    field,
                    oclc_response,
                    oclc_field,
                    title,
                    cursor
                )
                conn.commit()
            except Exception as err:
                print(err)
        else:
            print('Missing database connection.')

    def replace_fields(self, oclc_001_value, record, substitutions, oclc_response):
        """
        Handles all OCLC field replacements
        :param oclc_001_value: the 001 value from OCLC
        :param record: the record node
        :param substitutions: the array of substitution tags
        :param oclc_response: the reponse from OCLC
        :return:
        """
        # Assure OCLC values are in 001 and 003. Alma load will generate 035.
        # Do this after title validation.
        if oclc_001_value:
            # Update 001 with the value returned in the OCLC API response. This
            # can vary from the original value in the input records.
            self.__add_oclc_001_003(record, oclc_001_value)
            self.updated_001_count += 1
            self.updated_003_count += 1
        else:
            raise Exception('Something is wrong, OCLC response missing 001.')

        # Replace the leader with OCLC leader value.
        self.__replace_leader(record, oclc_response)
        self.updated_leader_count += 1

        # Remaining field substitutions.
        if '006' in substitutions:
            self.__control_field_update(record, '006',
                                        oclc_response)
        if '007' in substitutions:
            self.__control_field_update(record, '007',
                                        oclc_response)
        if '008' in substitutions:
            self.__control_field_update(record, '008',
                                        oclc_response)
        if '024' in substitutions:
            self.__data_field_update(record, '024',
                                     oclc_response)
        if '035' in substitutions:
            self.__data_field_update(record, '035',
                                     oclc_response)
        if '028' in substitutions:
            self.__data_field_update(record, '028',
                                     oclc_response)
        if '041' in substitutions:
            self.__data_field_update(record, '041',
                                     oclc_response)
        if '043' in substitutions:
            self.__data_field_update(record, '043',
                                     oclc_response)
        if '082' in substitutions:
            self.__data_field_update(record, '082',
                                     oclc_response)
        if '084' in substitutions:
            self.__data_field_update(record, '084',
                                     oclc_response)
        if '100' in substitutions:
            self.__data_field_update(record, '100',
                                     oclc_response)
        if '110' in substitutions:
            self.__data_field_update(record, '110',
                                     oclc_response)
        if '111' in substitutions:
            self.__data_field_update(record, '111',
                                     oclc_response)
        if '130' in substitutions:
            self.__data_field_update(record, '130',
                                     oclc_response)
        if '222' in substitutions:
            self.__data_field_update(record, '222',
                                     oclc_response)
        if '240' in substitutions:
            self.__data_field_update(record, '240',
                                     oclc_response)
        if '245' in substitutions:
            self.__data_field_update(record, '245',
                                     oclc_response)
        if '246' in substitutions:
            self.__data_field_update(record, '246',
                                     oclc_response)
        if '247' in substitutions:
            self.__data_field_update(record, '247',
                                     oclc_response)
        if '250' in substitutions:
            self.__data_field_update(record, '250',
                                     oclc_response)
        if '264' in substitutions:
            self.__data_field_update(record, '264',
                                     oclc_response)
        if '300' in substitutions:
            self.__data_field_update(record, '300',
                                     oclc_response)
        if '337' in substitutions:
            self.__data_field_update(record, '337',
                                     oclc_response)
        if '340' in substitutions:
            self.__data_field_update(record, '340',
                                     oclc_response)
        if '362' in substitutions:
            self.__data_field_update(record, '362',
                                     oclc_response)
        if '386' in substitutions:
            self.__data_field_update(record, '386',
                                     oclc_response)
        if '490' in substitutions:
            self.__data_field_update(record, '490',
                                     oclc_response)
        if '500' in substitutions:
            self.__data_field_update(record, '500',
                                         oclc_response)
        if '505' in substitutions:
            self.__data_field_update(record, '505',
                                     oclc_response)
        if '510' in substitutions:
            self.__data_field_update(record, '510',
                                     oclc_response)
        if '511' in substitutions:
            self.__data_field_update(record, '511',
                                     oclc_response)
        if '520' in substitutions:
            self.__data_field_update(record, '520',
                                     oclc_response)
        if '521' in substitutions:
            self.__data_field_update(record, '521',
                                     oclc_response)
        if '526' in substitutions:
            self.__data_field_update(record, '526',
                                     oclc_response)
        if '533' in substitutions:
            self.__data_field_update(record, '533',
                                     oclc_response)
        if '538' in substitutions:
            self.__data_field_update(record, '538',
                                     oclc_response)
        if '541' in substitutions:
            self.__data_field_update(record, '541',
                                     oclc_response)
        if '550' in substitutions:
            self.__data_field_update(record, '550',
                                     oclc_response)
        if '600' in substitutions:
            self.__data_field_update(record, '600',
                                     oclc_response)
        if '610' in substitutions:
            self.__data_field_update(record, '610',
                                     oclc_response)
        if '611' in substitutions:
            self.__data_field_update(record, '611',
                                     oclc_response)
        if '630' in substitutions:
            self.__data_field_update(record, '630',
                                     oclc_response)
        if '650' in substitutions:
            self.__data_field_update(record, '650',
                                     oclc_response)
        if '651' in substitutions:
            self.__data_field_update(record, '651',
                                     oclc_response)
        if '655' in substitutions:
            self.__data_field_update(record, '655',
                                     oclc_response)
        if '700' in substitutions:
            self.__data_field_update(record, '700',
                                     oclc_response)
        if '710' in substitutions:
            self.__data_field_update(record, '710',
                                     oclc_response)
        if '730' in substitutions:
            self.__data_field_update(record, '730',
                                     oclc_response)
        if '740' in substitutions:
            self.__data_field_update(record, '740',
                                     oclc_response)
        if '752' in substitutions:
            self.__data_field_update(record, '752',
                                     oclc_response)
        if '760' in substitutions:
            self.__data_field_update(record, '760',
                                     oclc_response)
        if '765' in substitutions:
            self.__data_field_update(record, '765',
                                     oclc_response)
        if '776' in substitutions:
            self.__data_field_update(record, '776',
                                     oclc_response)
        if '780' in substitutions:
            self.__data_field_update(record, '780',
                                     oclc_response)
        if '830' in substitutions:
            self.__data_field_update(record, '830',
                                     oclc_response)
        if '850' in substitutions:
            self.__data_field_update(record, '850',
                                     oclc_response)
