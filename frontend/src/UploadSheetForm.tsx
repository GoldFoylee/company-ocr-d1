import { useState, type FormEvent } from 'react'

import type { SheetUploadInput } from './api'

type UploadSheetFormProps = {
  isUploading: boolean
  error: string | null
  onUpload: (input: SheetUploadInput) => Promise<void>
}

export function UploadSheetForm({ isUploading, error, onUpload }: UploadSheetFormProps) {
  const [image, setImage] = useState<File | null>(null)
  const [vehicle, setVehicle] = useState('')
  const [branch, setBranch] = useState('')
  const [sheetDate, setSheetDate] = useState('')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (image) void onUpload({ image, vehicle: vehicle.trim(), branch: branch.trim(), sheetDate })
  }

  return (
    <section className="upload-panel" aria-labelledby="upload-title">
      <div className="upload-panel__copy">
        <p className="eyebrow">New sheet</p>
        <h2 id="upload-title">Upload and process</h2>
        <p>Choose one image. OCR runs synchronously and can take about 80 seconds.</p>
      </div>
      <form className="upload-form" onSubmit={handleSubmit}>
        <label>
          <span>Sheet image</span>
          <input
            type="file"
            accept="image/jpeg,image/png"
            required
            disabled={isUploading}
            onChange={(event) => setImage(event.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          <span>Vehicle number</span>
          <input
            value={vehicle}
            required
            disabled={isUploading}
            onChange={(event) => setVehicle(event.target.value)}
          />
        </label>
        <label>
          <span>Branch</span>
          <input
            value={branch}
            required
            disabled={isUploading}
            onChange={(event) => setBranch(event.target.value)}
          />
        </label>
        <label>
          <span>Sheet date</span>
          <input
            type="date"
            value={sheetDate}
            required
            disabled={isUploading}
            onChange={(event) => setSheetDate(event.target.value)}
          />
        </label>
        <button type="submit" disabled={isUploading || image === null}>
          {isUploading ? 'Processing sheet…' : 'Process sheet'}
        </button>
      </form>
      {isUploading && (
        <p className="processing-state" role="status">
          Processing sheet… Keep this page open while OCR finishes.
        </p>
      )}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </section>
  )
}
