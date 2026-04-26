"""Mapping helpers for market API responses."""

from __future__ import annotations

from app.api.market_schemas import (
    DepreciationPoint,
    MarketImage,
    MarketLotDetail,
    MarketLotListItem,
)
from app.models.auction_lot import AuctionLot


def lot_list_item(lot: AuctionLot) -> MarketLotListItem:
    return MarketLotListItem(
        id=lot.id,
        source=lot.source,
        canonical_url=lot.canonical_url,
        auction_status=lot.auction_status,
        sold_price=lot.sold_price,
        high_bid=lot.high_bid,
        bid_count=lot.bid_count,
        currency=lot.currency,
        ended_at=lot.ended_at,
        year=lot.year,
        make=lot.make,
        model=lot.model,
        trim=lot.trim,
        mileage=lot.mileage,
        exterior_color=lot.exterior_color,
        transmission=lot.transmission,
        title=lot.title,
        subtitle=lot.subtitle,
        image_count=len(lot.images),
    )


def depreciation_point(lot: AuctionLot) -> DepreciationPoint:
    return DepreciationPoint(
        id=lot.id,
        ended_at=lot.ended_at,
        year=lot.year,
        make=lot.make,
        model=lot.model,
        trim=lot.trim,
        mileage=lot.mileage,
        exterior_color=lot.exterior_color,
        transmission=lot.transmission,
        sold_price=lot.sold_price,
        high_bid=lot.high_bid,
        auction_status=lot.auction_status,
        source=lot.source,
        canonical_url=lot.canonical_url,
        title=lot.title,
    )


def lot_detail(lot: AuctionLot) -> MarketLotDetail:
    payload = {
        field: getattr(lot, field)
        for field in MarketLotDetail.model_fields
        if field != "images"
    }
    return MarketLotDetail(
        **payload,
        images=[
            MarketImage(
                id=image.id,
                image_url=image.image_url,
                position=image.position,
                caption=image.caption,
            )
            for image in sorted(lot.images, key=lambda image: image.position)
        ],
    )
