import './shared.css'

import { art01 } from './variants/art-01'
import { art02 } from './variants/art-02'
import { art03 } from './variants/art-03'
import { art04 } from './variants/art-04'
import { art05 } from './variants/art-05'
import { art06 } from './variants/art-06'
import { art07 } from './variants/art-07'
import { art08 } from './variants/art-08'
import { art09 } from './variants/art-09'
import { art10 } from './variants/art-10'
import type { SplashVariantMeta, SplashVariantModule } from './types'

const modules: SplashVariantModule[] = [
  art01,
  art02,
  art03,
  art04,
  art05,
  art06,
  art07,
  art08,
  art09,
  art10,
]

export const SPLASH_VARIANTS: SplashVariantMeta[] = modules.flatMap((m) => m.meta)

export const SPLASH_VARIANT_COUNT = SPLASH_VARIANTS.length

export function renderSplashVariant(
  id: number,
  props: Parameters<SplashVariantModule['render']>[1],
) {
  for (const mod of modules) {
    if (mod.meta.some((m) => m.id === id)) {
      return mod.render(id, props)
    }
  }
  return modules[0]?.render(modules[0].meta[0]?.id ?? 1, props) ?? null
}
