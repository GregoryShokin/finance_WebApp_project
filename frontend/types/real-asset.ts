export type RealAssetType = 'real_estate' | 'car' | 'other';

export type RealAsset = {
  id: number;
  asset_type: RealAssetType | string;
  name: string;
  estimated_value: number | string;
  linked_account_id: number | null;
  updated_at: string;
};

export type RealAssetPayload = {
  asset_type: RealAssetType;
  name: string;
  estimated_value: number;
  linked_account_id?: number | null;
};
