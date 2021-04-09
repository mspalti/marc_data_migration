import urllib.request
import xml.etree.ElementTree as ET
import re


class OclcConnector:

    def get_oclc_response(self, oclc, oclc_developer_key):
        # Insurance
        lookup = oclc.replace('ocn', '').replace('ocm', '').replace('on', '')
        # Odd thing that is in at least one record. This obviously should never happen.
        control_character_replacement = re.compile('\s+\d+$')
        lookup = re.sub(control_character_replacement, '', lookup)
        path = 'http://www.worldcat.org/webservices/catalog/content/' + lookup + '?wskey=' + oclc_developer_key
        print(path)
        with urllib.request.urlopen(path) as response:
            xml_response = response.read().decode()
            try:
                return ET.fromstring(xml_response)
            except:
                print('Cannot parse marcxml response.')






