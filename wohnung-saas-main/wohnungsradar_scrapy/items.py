import scrapy


class ApartmentItem(scrapy.Item):
    job_id = scrapy.Field()
    source = scrapy.Field()
    external_id = scrapy.Field()
    url = scrapy.Field()
    title = scrapy.Field()
    description = scrapy.Field()
    price = scrapy.Field()
    price_total = scrapy.Field()
    rooms = scrapy.Field()
    size = scrapy.Field()
    address = scrapy.Field()
    city = scrapy.Field()
    postal_code = scrapy.Field()
    region_code = scrapy.Field()
    contact_name = scrapy.Field()
    contact_phone = scrapy.Field()
    published_at = scrapy.Field()
    raw = scrapy.Field()
