/**
 * A fan with a calculator, for the Elo ledger specs (issue #183): reads a
 * worked step's printed operands, "→ 40 × 1.352 × (1 − 0.5787) = +22.8",
 * and multiplies them in exact decimal arithmetic, so no floating-point
 * rounding muddies the comparison with the printed shift. Test-side only:
 * the app itself computes none of this.
 */

/** A printed decimal held exactly: "1.352" is `{ digits: 1352n, places: 3 }`. */
interface Printed {
  digits: bigint
  places: number
}

/** Reads a number as the panel printed it ("1,500", "+22.8", "−8.1", "½"). */
function printed(text: string): Printed {
  const plain = text.replace(/[,+]/g, '').replace('−', '-').replace('½', '0.5')
  const [whole = '', fraction = ''] = plain.split('.')
  return { digits: BigInt(`${whole}${fraction}`), places: fraction.length }
}

function atPlaces(value: Printed, places: number): bigint {
  return value.digits * 10n ** BigInt(places - value.places)
}

const OPERANDS =
  /→ ([\d,.]+) × ([\d.]+) × \((1|½|0) − ([\d.]+)\) = ([+−]?[\d,.]+)$/

/** The printed k × multiplier × (result − win expectancy), beside the printed shift. */
function calculatorCheck(work: string): { product: Printed; shift: Printed } {
  const match = OPERANDS.exec(work)
  if (match === null) {
    throw new Error(`no operands in worked step: ${work}`)
  }
  const [, k = '', multiplier = '', result = '', expectancy = '', shift = ''] =
    match
  const outcome = printed(result)
  const winExpectancy = printed(expectancy)
  const places = Math.max(outcome.places, winExpectancy.places)
  const kValue = printed(k)
  const multiplierValue = printed(multiplier)
  return {
    product: {
      digits:
        kValue.digits *
        multiplierValue.digits *
        (atPlaces(outcome, places) - atPlaces(winExpectancy, places)),
      places: kValue.places + multiplierValue.places + places,
    },
    shift: printed(shift),
  }
}

/** Rounds half away from zero, the way the panel's Intl formatter rounds the shift. */
function roundedTo(value: Printed, places: number): bigint {
  if (value.places <= places) {
    return atPlaces(value, places)
  }
  const divisor = 10n ** BigInt(value.places - places)
  const magnitude = value.digits < 0n ? -value.digits : value.digits
  const rounded =
    magnitude / divisor + ((magnitude % divisor) * 2n >= divisor ? 1n : 0n)
  return value.digits < 0n ? -rounded : rounded
}

/** Whether the printed operands' product rounds, at 1 decimal, exactly to the printed shift. */
export function roundsToPrintedShift(work: string): boolean {
  const { product, shift } = calculatorCheck(work)
  return roundedTo(product, 1) === atPlaces(shift, 1)
}

/** Whether the printed operands' product is within a tenth of the printed shift (the footnote's promise). */
export function withinATenthOfPrintedShift(work: string): boolean {
  const { product, shift } = calculatorCheck(work)
  const gap = product.digits - atPlaces(shift, product.places)
  const tenth = 10n ** BigInt(product.places - 1)
  return gap <= tenth && gap >= -tenth
}
