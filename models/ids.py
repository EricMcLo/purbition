import random
import string


def generate_share_id(length=12):
    alphabet = string.ascii_lowercase + string.ascii_uppercase + string.digits
    return ''.join(random.choice(alphabet) for _ in range(length))
