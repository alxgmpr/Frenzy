from mongoengine import *


class Sale(Document):
    shopify_id = IntField()
    handle = StringField(max_length=12)
    description = StringField()
    title = StringField()
    image_url = URLField()
    start_time = DateTimeField()
    is_hidden = BooleanField(default=False)
    is_sold_out = BooleanField(default=False)
    is_pickup = BooleanField(default=False)
    shipping_message = StringField()
