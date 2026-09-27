import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind class lists, letting later classes win. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
