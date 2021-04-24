fields_dict = {
    '006': 0,
    '007': 0,
    '008': 0,
    '024': 0,
    '028': 0,
    '041': 0,
    '043': 0,
    '082': 0,
    '084': 0,
    '100': 0,
    '110': 0,
    '111': 0,
    '130': 0,
    '222': 0,
    '240': 0,
    '245': 0,
    '246': 0,
    '247': 0,
    '250': 0,
    '264': 0,
    '300': 0,
    '337': 0,
    '340': 0,
    '362': 0,
    '386': 0,
    '490': 0,
    '505': 0,
    '510': 0,
    '511': 0,
    '520': 0,
    '521': 0,
    '526': 0,
    '533': 0,
    '538': 0,
    '541': 0,
    '550': 0,
    '590': 0,
    '600': 0,
    '610': 0,
    '611': 0,
    '630': 0,
    '650': 0,
    '651': 0,
    '655': 0,
    '700': 0,
    '710': 0,
    '730': 0,
    '740': 0,
    '752': 0,
    '760': 0,
    '765': 0,
    '780': 0,
    '830': 0,
    '850': 0
}


def update_field_count(field):
    fields_dict[field] += 1


def get_field_count():
    return fields_dict
