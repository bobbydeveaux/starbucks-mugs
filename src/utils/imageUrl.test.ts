import { describe, it, expect } from 'vitest';
import { getCarImageUrl } from './imageUrl';

// ---------------------------------------------------------------------------
// Fixtures: Sample car models with expected transformations
// ---------------------------------------------------------------------------

interface TestCase {
  brand: string;
  modelName: string;
  expected: string;
  description: string;
}

const testCases: TestCase[] = [
  // Ferrari models
  {
    brand: 'ferrari',
    modelName: '250 Testa Rossa',
    expected: '/images/ferrari/250-testa-rossa.jpg',
    description: 'Ferrari with multiple spaces',
  },
  {
    brand: 'ferrari',
    modelName: '250 GT California',
    expected: '/images/ferrari/250-gt-california.jpg',
    description: 'Ferrari with abbreviation',
  },
  {
    brand: 'ferrari',
    modelName: '250 GTO',
    expected: '/images/ferrari/250-gto.jpg',
    description: 'Ferrari with short model name',
  },
  {
    brand: 'ferrari',
    modelName: 'F40',
    expected: '/images/ferrari/f40.jpg',
    description: 'Ferrari with alphanumeric name',
  },
  {
    brand: 'ferrari',
    modelName: 'Testarossa',
    expected: '/images/ferrari/testarossa.jpg',
    description: 'Ferrari single word',
  },

  // Lamborghini models
  {
    brand: 'lamborghini',
    modelName: '350 GT',
    expected: '/images/lamborghini/350-gt.jpg',
    description: 'Lamborghini with numbers and abbreviation',
  },
  {
    brand: 'lamborghini',
    modelName: 'Miura P400',
    expected: '/images/lamborghini/miura-p400.jpg',
    description: 'Lamborghini with mixed alphanumeric',
  },
  {
    brand: 'lamborghini',
    modelName: 'Countach LP400',
    expected: '/images/lamborghini/countach-lp400.jpg',
    description: 'Lamborghini with model variant',
  },
  {
    brand: 'lamborghini',
    modelName: 'Countach LP500S',
    expected: '/images/lamborghini/countach-lp500s.jpg',
    description: 'Lamborghini with alphanumeric suffix',
  },
  {
    brand: 'lamborghini',
    modelName: 'Countach 25th Anniversary',
    expected: '/images/lamborghini/countach-25th-anniversary.jpg',
    description: 'Lamborghini with numeric suffix and text',
  },

  // Models with accents
  {
    brand: 'lamborghini',
    modelName: 'Murciélago',
    expected: '/images/lamborghini/murcielago.jpg',
    description: 'Model with accent (é → e)',
  },
  {
    brand: 'lamborghini',
    modelName: 'Huracán LP610-4',
    expected: '/images/lamborghini/huracan-lp610-4.jpg',
    description: 'Model with accent and hyphenated suffix',
  },
  {
    brand: 'lamborghini',
    modelName: 'Huracán Performante',
    expected: '/images/lamborghini/huracan-performante.jpg',
    description: 'Model with accent in first word',
  },
  {
    brand: 'lamborghini',
    modelName: 'Reventón',
    expected: '/images/lamborghini/reventon.jpg',
    description: 'Model with accent at end',
  },

  // Complex model names
  {
    brand: 'lamborghini',
    modelName: 'Gallardo LP570-4 Superleggera',
    expected: '/images/lamborghini/gallardo-lp570-4-superleggera.jpg',
    description: 'Complex model with multiple parts',
  },
  {
    brand: 'lamborghini',
    modelName: 'Aventador LP700-4',
    expected: '/images/lamborghini/aventador-lp700-4.jpg',
    description: 'Model with hyphenated numbers',
  },
  {
    brand: 'lamborghini',
    modelName: 'Countach LPI 800-4',
    expected: '/images/lamborghini/countach-lpi-800-4.jpg',
    description: 'Model with mixed alphanumeric and hyphenated suffix',
  },

  // Edge cases
  {
    brand: 'ferrari',
    modelName: 'F8 Tributo',
    expected: '/images/ferrari/f8-tributo.jpg',
    description: 'Model starting with letter + number',
  },
  {
    brand: 'lamborghini',
    modelName: 'Sesto Elemento',
    expected: '/images/lamborghini/sesto-elemento.jpg',
    description: 'Model with two Italian words',
  },
];

// ---------------------------------------------------------------------------
// Tests: Basic functionality
// ---------------------------------------------------------------------------

describe('getCarImageUrl', () => {
  describe('Basic URL generation', () => {
    it('returns a string', () => {
      const result = getCarImageUrl('ferrari', 'Testarossa');
      expect(typeof result).toBe('string');
    });

    it('returns a URL starting with /images/', () => {
      const result = getCarImageUrl('ferrari', 'F40');
      expect(result).toMatch(/^\/images\//);
    });

    it('includes the brand in the URL path', () => {
      const result = getCarImageUrl('ferrari', 'F40');
      expect(result).toContain('/ferrari/');
    });

    it('ends with .jpg', () => {
      const result = getCarImageUrl('lamborghini', 'Murciélago');
      expect(result).toMatch(/\.jpg$/);
    });

    it('returns correct format: /images/{brand}/{model}.jpg', () => {
      const result = getCarImageUrl('ferrari', 'F40');
      expect(result).toMatch(/^\/images\/[a-z]+\/[a-z0-9-]+\.jpg$/);
    });
  });

  // -------------------------------------------------------------------------
  // Tests: Transformation rules
  // -------------------------------------------------------------------------

  describe('Lowercase conversion', () => {
    it('converts uppercase letters to lowercase', () => {
      const result = getCarImageUrl('ferrari', 'TESTAROSSA');
      expect(result).toContain('testarossa');
      expect(result).not.toContain('TESTAROSSA');
    });

    it('converts mixed case to lowercase', () => {
      const result = getCarImageUrl('lamborghini', 'Murciélago');
      expect(result).toContain('murcielago');
    });
  });

  describe('Space handling', () => {
    it('replaces spaces with hyphens', () => {
      const result = getCarImageUrl('ferrari', '250 Testa Rossa');
      expect(result).toContain('250-testa-rossa');
      expect(result).not.toContain(' ');
    });

    it('handles multiple consecutive spaces', () => {
      const result = getCarImageUrl('ferrari', '250  Testa   Rossa');
      expect(result).toContain('250-testa-rossa');
    });

    it('handles leading and trailing spaces', () => {
      const result1 = getCarImageUrl('ferrari', '  250 Testa Rossa');
      const result2 = getCarImageUrl('ferrari', '250 Testa Rossa  ');
      const result3 = getCarImageUrl('ferrari', '250 Testa Rossa');
      // Should all normalize to same value
      expect(result1).toBe(result3);
      expect(result2).toBe(result3);
    });
  });

  describe('Accent/diacritic removal', () => {
    it('removes accent from é', () => {
      const result = getCarImageUrl('lamborghini', 'Murciélago');
      expect(result).toContain('murcielago');
      expect(result).not.toContain('é');
    });

    it('removes accent from á', () => {
      const result = getCarImageUrl('ferrari', 'Modèna');
      expect(result).toContain('modena');
    });

    it('removes accent from ó', () => {
      const result = getCarImageUrl('lamborghini', 'Reventón');
      expect(result).toContain('reventon');
    });

    it('handles models with multiple accented characters', () => {
      const result = getCarImageUrl('lamborghini', 'Huracán');
      expect(result).toContain('huracan');
    });
  });

  describe('Hyphenated model variants', () => {
    it('preserves hyphens in model numbers', () => {
      const result = getCarImageUrl('lamborghini', 'Aventador LP700-4');
      expect(result).toContain('aventador-lp700-4');
    });

    it('handles complex hyphenated names', () => {
      const result = getCarImageUrl('lamborghini', 'Countach LP570-4 Superleggera');
      expect(result).toContain('countach-lp570-4-superleggera');
    });

    it('preserves numbers after hyphens', () => {
      const result = getCarImageUrl('lamborghini', 'Huracán LP610-4');
      expect(result).toContain('huracan-lp610-4');
    });
  });

  // -------------------------------------------------------------------------
  // Tests: Test cases from fixture data
  // -------------------------------------------------------------------------

  describe('Known model transformations', () => {
    testCases.forEach((testCase) => {
      it(`${testCase.description}: "${testCase.modelName}" → "${testCase.expected.split('/').pop()}"`, () => {
        const result = getCarImageUrl(testCase.brand, testCase.modelName);
        expect(result).toBe(testCase.expected);
      });
    });
  });

  // -------------------------------------------------------------------------
  // Tests: Brand parameter
  // -------------------------------------------------------------------------

  describe('Brand parameter handling', () => {
    it('includes ferrari brand in URL', () => {
      const result = getCarImageUrl('ferrari', 'F40');
      expect(result).toContain('/ferrari/');
    });

    it('includes lamborghini brand in URL', () => {
      const result = getCarImageUrl('lamborghini', 'Miura');
      expect(result).toContain('/lamborghini/');
    });

    it('preserves brand case in URL path', () => {
      const result = getCarImageUrl('ferrari', 'F40');
      expect(result).toContain('/ferrari/'); // brand stays lowercase
    });

    it('handles different brands', () => {
      const ferrari = getCarImageUrl('ferrari', 'F40');
      const lambo = getCarImageUrl('lamborghini', 'Murciélago');
      expect(ferrari).toContain('/ferrari/');
      expect(lambo).toContain('/lamborghini/');
      expect(ferrari).not.toEqual(lambo);
    });
  });

  // -------------------------------------------------------------------------
  // Tests: Edge cases
  // -------------------------------------------------------------------------

  describe('Edge cases', () => {
    it('handles single-word model names', () => {
      const result = getCarImageUrl('lamborghini', 'Espada');
      expect(result).toContain('espada');
      expect(result).toMatch(/^\/images\/lamborghini\/[a-z]+\.jpg$/);
    });

    it('handles model names with only numbers', () => {
      const result = getCarImageUrl('ferrari', '599');
      expect(result).toContain('599');
    });

    it('handles model names with numbers and letters', () => {
      const result = getCarImageUrl('ferrari', 'F8 Tributo');
      expect(result).toContain('f8-tributo');
    });

    it('handles empty model name gracefully', () => {
      const result = getCarImageUrl('ferrari', '');
      expect(result).toBe('/images/ferrari/.jpg');
    });

    it('removes special characters', () => {
      const result = getCarImageUrl('ferrari', 'Model-Name!@#$%');
      // Special characters should be removed, keeping only alphanumerics and hyphens
      expect(result).toContain('model-name');
    });

    it('converts tabs to hyphens', () => {
      const result = getCarImageUrl('ferrari', '250\tTesta');
      expect(result).not.toContain('\t');
    });

    it('handles newlines in model name', () => {
      const result = getCarImageUrl('ferrari', '250\nTesta');
      expect(result).not.toContain('\n');
    });
  });

  // -------------------------------------------------------------------------
  // Tests: Consistency and immutability
  // -------------------------------------------------------------------------

  describe('Consistency and immutability', () => {
    it('produces same output for same input (idempotent)', () => {
      const model = 'Huracán LP610-4';
      const result1 = getCarImageUrl('lamborghini', model);
      const result2 = getCarImageUrl('lamborghini', model);
      expect(result1).toBe(result2);
    });

    it('does not mutate input parameters', () => {
      const brand = 'ferrari';
      const modelName = 'F40';
      const originalBrand = brand;
      const originalModel = modelName;

      getCarImageUrl(brand, modelName);

      expect(brand).toBe(originalBrand);
      expect(modelName).toBe(originalModel);
    });

    it('different models produce different URLs', () => {
      const url1 = getCarImageUrl('ferrari', 'F40');
      const url2 = getCarImageUrl('ferrari', 'F8 Tributo');
      expect(url1).not.toBe(url2);
    });

    it('same model with different brands produce different URLs', () => {
      const ferrari = getCarImageUrl('ferrari', 'Miura'); // hypothetical
      const lambo = getCarImageUrl('lamborghini', 'Miura');
      expect(ferrari).not.toBe(lambo);
    });
  });

  // -------------------------------------------------------------------------
  // Tests: Real-world Ferrari models
  // -------------------------------------------------------------------------

  describe('Real Ferrari models', () => {
    const ferrariModels = [
      ['250 Testa Rossa', '250-testa-rossa'],
      ['250 GT California', '250-gt-california'],
      ['250 GTO', '250-gto'],
      ['F40', 'f40'],
      ['F50', 'f50'],
      ['Enzo Ferrari', 'enzo-ferrari'],
      ['LaFerrari', 'laferrari'],
      ['SF90 Stradale', 'sf90-stradale'],
    ];

    ferrariModels.forEach(([model, expected]) => {
      it(`transforms "${model}" correctly`, () => {
        const result = getCarImageUrl('ferrari', model);
        expect(result).toContain(expected);
      });
    });
  });

  // -------------------------------------------------------------------------
  // Tests: Real-world Lamborghini models
  // -------------------------------------------------------------------------

  describe('Real Lamborghini models', () => {
    const lamboModels = [
      ['Miura P400', 'miura-p400'],
      ['Countach LP400', 'countach-lp400'],
      ['Diablo', 'diablo'],
      ['Murciélago', 'murcielago'],
      ['Gallardo', 'gallardo'],
      ['Aventador', 'aventador'],
      ['Huracán', 'huracan'],
      ['Urus', 'urus'],
    ];

    lamboModels.forEach(([model, expected]) => {
      it(`transforms "${model}" correctly`, () => {
        const result = getCarImageUrl('lamborghini', model);
        expect(result).toContain(expected);
      });
    });
  });
});
