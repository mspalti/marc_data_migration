import re

from modules.location_mapping import LocationMapper


class PncaLocalModification:
    """
    The more idiosyncratic parts of the PNCA migration live here.
    """

    streaming_video_count = 0
    ebook_count = 0
    online_periodical_count = 0

    @staticmethod
    def get_local_fields():
        """
        Fields that should be marked as local before ingesting into Alma.
        :return:
        """
        fields = ['590', '690', '852', '900', '918', '921', '994', '998', '936', '991']
        return fields

    def is_online(self, record):
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

    def print_online_record_counts(self):
        print('Ebook record count: ' + str(self.ebook_count))
        print('Online periodical record count: ' + str(self.online_periodical_count))
        print('Streaming video record count: ' + str(self.streaming_video_count))
        total_electronic_records = self.streaming_video_count + self.ebook_count + self.online_periodical_count
        print('Total electronic records: ' + str(total_electronic_records))

    @staticmethod
    def add_inventory(record):
        """
        Copy the inventory note to 852(i)
        :param record: pymarc record
        :return:
        """
        fields = record.get_fields('852')
        for field in fields:
            subs = field.subfields_as_dict()
            sub = subs["1"]
            for s in sub:
                arr = s.split('|')
                for item in arr:
                    if re.match('^Inventory', item):
                        field.add_subfield('i', item)

    @staticmethod
    def add_funds(record):
        """
        Copy the funds note to 852(f)
        """
        fields = record.get_fields('852')
        for field in fields:
            subs = field.subfields_as_dict()
            sub = subs['1']
            for s in sub:
                arr = s.split('|')
                for item in arr:
                    if re.match('^Fund', item):
                        field.add_subfield('f', 'PNCA ' + item)

    def add_location(self, record, oclc_number):
        """
        Add a location based on call number or 852(b)
        :param record:
        :param oclc_number:
        :return:
        """
        location_mapper = LocationMapper()
        location_field = self.__get_852b(record)
        # This is a hack for locations that cannot be determined by
        # using the PNCA call number.
        if location_field == '1st Floor CDs' or location_field == 'OVERSIZE PERIODICALS':
            try:
                location = location_mapper.get_location(location_field)
                self.__replace_location(record, location)
            except Exception as err:
                print('error replacing location field.')
                print(err)

        else:
            call_number = self.__get_call_number(record)
            if not call_number:
                if oclc_number:
                    print('Missing call number for: ' + oclc_number)
                else:
                    print('Missing call number for: ' + record.title())
            else:
                try:
                    location = location_mapper.get_location_by_callnumber(call_number)
                    if location:
                        self.__add_location_to_record(record, location)
                except Exception as err:
                    print('error adding location field.')
                    print(err)

    @staticmethod
    def __get_852b(record):
        """
        Returns value of 852(b) if available.
        :param record: pymarc record
        :return:
        """
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
        Returns call number found in 852(h)
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

    @staticmethod
    def __replace_location(record, location):
        """
        Replaces the current value of 852(b)
        :param record: pymarc record
        :param location: location
        :return:
        """
        if len(record.get_fields('852')) > 0:
            try:
                fields = record.get_fields('852')
                for field in fields:
                    field.delete_subfield('b')
                    field.add_subfield('b', location, 1)
            except Exception as err:
                print('Error replacing location in record.')
                print(err)

    @staticmethod
    def __add_location_to_record(record, location):
        """
        Adds 852(b) to the record
        :param record: pymarc record
        :param location: location code
        :return:
        """
        if len(record.get_fields('852')) > 0:
            try:
                fields = record.get_fields('852')
                for field in fields:
                    field.add_subfield('b', location, 1)
            except Exception as err:
                print('Error adding location to record.')
                print(err)