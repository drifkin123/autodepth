export const SUPPORTED_MAKES = [
  'Porsche',
  'Ferrari',
  'Lamborghini',
  'McLaren',
  'Mercedes-AMG',
  'Audi',
  'Chevrolet',
  'Lotus',
] as const

export type SupportedMake = (typeof SUPPORTED_MAKES)[number]

export const MODELS_BY_MAKE: Record<SupportedMake, string[]> = {
  Porsche: [
    '911 GT3',
    '911 GT3 RS',
    '911 Turbo S',
    'Cayman GT4',
    '918 Spyder',
  ],
  Ferrari: [
    '458 Italia',
    '458 Spider',
    '458 Speciale',
    '488 GTB',
    '488 Pista',
    'F8 Tributo',
    'F8 Spider',
    'SF90 Stradale',
    'Roma',
  ],
  Lamborghini: [
    'Huracán LP610-4',
    'Huracán EVO',
    'Huracán STO',
    'Huracán Performante',
    'Urus',
    'Urus S',
    'Urus Performante',
    'Aventador S',
    'Aventador SVJ',
  ],
  McLaren: [
    '570S',
    '600LT',
    '720S',
    '765LT',
    'Artura',
  ],
  'Mercedes-AMG': [
    'AMG GT',
    'AMG GT S',
    'AMG GT R',
    'AMG GT 63 S',
  ],
  Audi: [
    'R8 V10',
    'R8 V10 Performance',
    'RS6 Avant',
    'RS7',
  ],
  Chevrolet: [
    'Corvette C8 Stingray',
    'Corvette C8 Z06',
    'Corvette C8 E-Ray',
  ],
  Lotus: [
    'Emira V6',
    'Evora GT',
    'Exige S',
    'Exige Cup 430',
  ],
}

export const SALE_SOURCES = [
  'bring_a_trailer',
  'cars_and_bids',
  'rm_sotheby',
  'autotrader',
  'cars_com',
  'dealer',
  'private_seller',
] as const

/** Sources that provide confirmed sold prices */
export const AUCTION_SOURCES = [
  'bring_a_trailer',
  'cars_and_bids',
  'rm_sotheby',
] as const

/** Sources that provide asking/listing prices only */
export const LISTING_SOURCES = [
  'autotrader',
  'cars_com',
  'dealer',
  'private_seller',
] as const

export const BUY_WINDOW_LABELS: Record<string, string> = {
  depreciating_fast: 'Depreciating Fast',
  near_floor:        'Near Floor',
  at_floor:          'At Floor',
  appreciating:      'Appreciating',
}
