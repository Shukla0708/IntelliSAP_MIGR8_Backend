from pydantic import BaseModel


class ConfirmedFieldIn(BaseModel):
    source_field: str
    target_field: str  # "{sap_table}.{sap_field}", must be one of the mapping's candidates


class ConfirmMappingRequest(BaseModel):
    fields: list[ConfirmedFieldIn]
